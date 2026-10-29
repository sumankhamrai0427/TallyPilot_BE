import os
import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from model.models import (
    BankTransaction, ImportBatch, TransactionClassification,
    HumanReview, ApprovalRecord, TallySubmission, TransactionStatus, VoucherType
)
from database.repositories import (
    TransactionRepository, BatchRepository, LedgerRepository, AuditRepository
)
from helper.excel_reader import ExcelReaderService
from helper.local_llm import LocalLLMService
from helper.accounting_validator import AccountingValidatorService
from helper.voucher_builder import VoucherBuilderService
from helper.tally_client import TallyClientService
from utils.security import calculate_file_hash
from model.schemas import ClarifyTransactionRequest, ApproveTransactionRequest


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.tx_repo = TransactionRepository(db)
        self.batch_repo = BatchRepository(db)
        self.ledger_repo = LedgerRepository(db)
        self.audit_repo = AuditRepository(db)
        self.excel_reader = ExcelReaderService()
        self.llm_service = LocalLLMService()
        self.validator = AccountingValidatorService()
        self.tally_client = TallyClientService()

    def ingest_excel_file(self, file_path: str, filename: str) -> ImportBatch:
        # 1. Read file and check hash for duplicates
        file_hash, file_size, _ = self.excel_reader.read_and_validate_file(file_path)

        existing_batch = self.batch_repo.get_by_file_hash(file_hash)
        if existing_batch:
            self.audit_repo.log(
                action="DUPLICATE_FILE_REJECTED",
                summary=f"File {filename} rejected as duplicate of batch {existing_batch.batch_id}",
                details={"file_hash": file_hash, "original_batch_id": existing_batch.batch_id}
            )
            raise ValueError(f"Duplicate file detected. This file was previously imported in batch '{existing_batch.batch_id}'.")

        # 2. Create batch record
        batch_id_str = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
        batch = ImportBatch(
            batch_id=batch_id_str,
            filename=filename,
            file_path=file_path,
            file_hash=file_hash,
            file_size_bytes=file_size,
            status="PROCESSING"
        )
        self.batch_repo.create(batch)

        self.audit_repo.log(
            action="BATCH_UPLOADED",
            summary=f"Batch {batch_id_str} created for file {filename}",
            batch_id=batch.id
        )

        # 3. Parse transactions from file
        try:
            valid_rows, error_rows = self.excel_reader.parse_bank_statement(file_path)
            batch.total_rows = len(valid_rows) + len(error_rows)
            batch.parsed_rows = len(valid_rows)
            batch.failed_rows = len(error_rows)

            # Available ledgers from Tally master sync
            ledgers = [l.name for l in self.ledger_repo.list_all()]
            if not ledgers:
                sync_list, _ = self.tally_client.sync_ledgers_from_tally()
                for item in sync_list:
                    self.ledger_repo.upsert(item["name"], item["parent_group"])
                ledgers = [l.name for l in self.ledger_repo.list_all()]

            for row_data in valid_rows:
                tx = BankTransaction(
                    batch_id=batch.id,
                    source_row_index=row_data["source_row_index"],
                    transaction_date=row_data["transaction_date"],
                    value_date=row_data.get("value_date"),
                    bank_reference=row_data.get("bank_reference"),
                    narration=row_data["narration"],
                    debit_amount=row_data["debit_amount"],
                    credit_amount=row_data["credit_amount"],
                    balance=row_data.get("balance"),
                    raw_payload=row_data.get("raw_payload"),
                    status=TransactionStatus.PARSED.value
                )
                self.tx_repo.create(tx)

                # 4. Local AI Classification
                debit_f = float(row_data["debit_amount"])
                credit_f = float(row_data["credit_amount"])
                ai_prop, is_fallback = self.llm_service.classify_transaction(
                    narration=row_data["narration"],
                    debit_amount=debit_f,
                    credit_amount=credit_f,
                    available_ledgers=ledgers
                )

                classification = TransactionClassification(
                    transaction_id=tx.id,
                    model_name="rule_fallback_engine" if is_fallback else self.llm_service.model,
                    transaction_type=ai_prop.transaction_type,
                    suggested_voucher_type=ai_prop.suggested_voucher_type.value,
                    suggested_ledger=ai_prop.suggested_ledger,
                    contra_ledger=ai_prop.contra_ledger,
                    confidence=Decimal(str(round(ai_prop.confidence, 4))),
                    explanation=ai_prop.explanation,
                    ambiguity_reason=ai_prop.ambiguity_reason,
                    requires_human_review=ai_prop.requires_human_review,
                    is_fallback_rule=is_fallback
                )
                self.tx_repo.add_classification(classification)

                # 5. Deterministic Accounting Validation
                val_res = self.validator.validate_transaction(
                    tx=tx,
                    target_ledger=ai_prop.suggested_ledger,
                    voucher_type=ai_prop.suggested_voucher_type.value,
                    contra_ledger=ai_prop.contra_ledger,
                    available_ledgers=ledgers
                )

                # State machine transition
                if not val_res["is_valid"] or ai_prop.requires_human_review or ai_prop.confidence < self.llm_service.confidence_threshold:
                    tx.status = TransactionStatus.NEEDS_CLARIFICATION.value
                    tx.requires_review = True
                else:
                    tx.status = TransactionStatus.PENDING_APPROVAL.value
                    tx.requires_review = False

                self.tx_repo.update(tx)

            batch.status = "COMPLETED"
            self.batch_repo.update(batch)

            self.audit_repo.log(
                action="BATCH_PROCESSED",
                summary=f"Batch {batch_id_str} completed with {batch.parsed_rows} parsed, {batch.failed_rows} failed rows.",
                batch_id=batch.id
            )
            return batch

        except Exception as e:
            batch.status = "FAILED"
            batch.error_message = str(e)
            self.batch_repo.update(batch)
            self.audit_repo.log(
                action="BATCH_FAILED",
                summary=f"Batch {batch_id_str} failed: {str(e)}",
                batch_id=batch.id
            )
            raise

    def clarify_transaction(self, tx_id: int, req: ClarifyTransactionRequest) -> BankTransaction:
        tx = self.tx_repo.get_by_id(tx_id)
        if not tx:
            raise ValueError(f"Transaction ID {tx_id} not found.")

        if tx.status not in [TransactionStatus.NEEDS_CLARIFICATION.value, TransactionStatus.PARSED.value]:
            raise ValueError(f"Transaction status '{tx.status}' is not eligible for clarification.")

        review = HumanReview(
            transaction_id=tx.id,
            reviewer_user="finance_user",
            corrected_transaction_type=req.corrected_transaction_type,
            corrected_voucher_type=req.corrected_voucher_type.value,
            selected_ledger=req.selected_ledger,
            contra_ledger="HDFC Bank",
            reviewer_notes=req.reviewer_notes,
            resolution_action=req.resolution_action
        )
        self.tx_repo.add_review(review)

        # Re-run deterministic validation
        ledgers = [l.name for l in self.ledger_repo.list_all()]
        val_res = self.validator.validate_transaction(
            tx=tx,
            target_ledger=req.selected_ledger,
            voucher_type=req.corrected_voucher_type.value,
            contra_ledger="HDFC Bank",
            available_ledgers=ledgers
        )

        prev_status = tx.status
        if val_res["is_valid"]:
            tx.status = TransactionStatus.PENDING_APPROVAL.value
            tx.requires_review = False
        else:
            tx.status = TransactionStatus.NEEDS_CLARIFICATION.value
            tx.requires_review = True

        self.tx_repo.update(tx)

        self.audit_repo.log(
            action="TRANSACTION_CLARIFIED",
            summary=f"Transaction #{tx.id} clarified with ledger '{req.selected_ledger}'. New status: {tx.status}",
            transaction_id=tx.id,
            previous_status=prev_status,
            new_status=tx.status,
            details={"review_notes": req.reviewer_notes, "validation_errors": val_res["errors"]}
        )
        return tx

    def approve_and_post_transaction(self, tx_id: int, req: ApproveTransactionRequest) -> Dict[str, Any]:
        tx = self.tx_repo.get_by_id(tx_id)
        if not tx:
            raise ValueError(f"Transaction ID {tx_id} not found.")

        if tx.is_skipped:
            raise ValueError("Skipped transactions cannot be approved or submitted to Tally.")

        if tx.status != TransactionStatus.PENDING_APPROVAL.value:
            raise ValueError(f"Transaction #{tx.id} cannot be approved from status '{tx.status}'.")

        target_ledger = None
        voucher_type = None
        contra_ledger = "HDFC Bank"

        if tx.reviews:
            latest_review = tx.reviews[-1]
            target_ledger = latest_review.selected_ledger
            voucher_type = latest_review.corrected_voucher_type
            contra_ledger = latest_review.contra_ledger or "HDFC Bank"
        elif tx.classification:
            target_ledger = tx.classification.suggested_ledger
            voucher_type = tx.classification.suggested_voucher_type
            contra_ledger = tx.classification.contra_ledger or "HDFC Bank"

        if not target_ledger or not voucher_type:
            raise ValueError("Incomplete ledger or voucher type information. Clarification required first.")

        amount = tx.debit_amount if tx.debit_amount > 0 else tx.credit_amount

        # 1. Record explicit approval
        approval = ApprovalRecord(
            transaction_id=tx.id,
            approver_user=req.approver_user,
            voucher_type=voucher_type,
            primary_ledger=target_ledger,
            contra_ledger=contra_ledger,
            amount=amount,
            approval_notes=req.approval_notes
        )
        self.tx_repo.add_approval(approval)

        # 2. Move to SUBMITTING state
        prev_status = tx.status
        tx.status = TransactionStatus.SUBMITTING.value
        self.tx_repo.update(tx)

        # 3. Build XML voucher payload
        xml_payload = VoucherBuilderService.build_tally_voucher_xml(
            company_name=self.tally_client.company,
            voucher_type=voucher_type,
            voucher_date=tx.transaction_date,
            reference_number=tx.bank_reference or f"TX-{tx.id}",
            narration=tx.narration,
            amount=amount,
            primary_ledger=target_ledger,
            contra_ledger=contra_ledger
        )
        payload_hash = calculate_file_hash(xml_payload.encode("utf-8"))

        # 4. Durable TallySubmission record for idempotency
        submission = TallySubmission(
            transaction_id=tx.id,
            company_name=self.tally_client.company,
            voucher_type=voucher_type,
            voucher_date=tx.transaction_date,
            payload_hash=payload_hash,
            xml_payload=xml_payload,
            status="SUBMITTING"
        )
        self.db.add(submission)
        self.db.commit()
        self.db.refresh(submission)

        # 5. Submit to Tally Prime
        tally_res = self.tally_client.submit_voucher(xml_payload)

        submission.http_status_code = tally_res.get("http_status")
        submission.tally_response_raw = tally_res.get("raw_response")
        submission.tally_voucher_guid = tally_res.get("guid")

        if tally_res.get("success"):
            tx.status = TransactionStatus.PROCESSED.value
            submission.status = "SUCCESS"
            self.tx_repo.update(tx)
            self.db.commit()

            self.audit_repo.log(
                action="TALLY_VOUCHER_POSTED",
                summary=f"Transaction #{tx.id} successfully posted to Tally Prime (GUID: {tally_res.get('guid')})",
                transaction_id=tx.id,
                previous_status=prev_status,
                new_status=tx.status,
                details=tally_res
            )
            return {"success": True, "transaction_id": tx.id, "status": tx.status, "guid": tally_res.get("guid")}
        else:
            tx.status = TransactionStatus.FAILED.value
            submission.status = "FAILED"
            submission.error_message = tally_res.get("message")
            self.tx_repo.update(tx)
            self.db.commit()

            self.audit_repo.log(
                action="TALLY_POSTING_FAILED",
                summary=f"Failed to post Transaction #{tx.id} to Tally: {tally_res.get('message')}",
                transaction_id=tx.id,
                previous_status=prev_status,
                new_status=tx.status,
                details=tally_res
            )
            return {"success": False, "transaction_id": tx.id, "status": tx.status, "error": tally_res.get("message")}

    def skip_transaction(self, tx_id: int, reason: str) -> BankTransaction:
        tx = self.tx_repo.get_by_id(tx_id)
        if not tx:
            raise ValueError(f"Transaction ID {tx_id} not found.")

        prev_status = tx.status
        tx.is_skipped = True
        tx.skip_reason = reason
        tx.status = TransactionStatus.SKIPPED.value
        self.tx_repo.update(tx)

        self.audit_repo.log(
            action="TRANSACTION_SKIPPED",
            summary=f"Transaction #{tx.id} skipped by user. Reason: {reason}",
            transaction_id=tx.id,
            previous_status=prev_status,
            new_status=tx.status
        )
        return tx

    def retry_transaction(self, tx_id: int) -> BankTransaction:
        tx = self.tx_repo.get_by_id(tx_id)
        if not tx:
            raise ValueError(f"Transaction ID {tx_id} not found.")

        prev_status = tx.status
        tx.status = TransactionStatus.PENDING_APPROVAL.value
        self.tx_repo.update(tx)

        self.audit_repo.log(
            action="TRANSACTION_RESET_RETRY",
            summary=f"Transaction #{tx.id} reset to PENDING_APPROVAL for retry.",
            transaction_id=tx.id,
            previous_status=prev_status,
            new_status=tx.status
        )
        return tx

