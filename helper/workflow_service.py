import os
import uuid
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from model.models import (
    BankTransaction, ImportBatch, TransactionClassification,
    HumanReview, ApprovalRecord, TallySubmission, TransactionStatus, VoucherType,
    LedgerAccount, AccountGroup
)
from database.repositories import (
    TransactionRepository, BatchRepository, LedgerRepository, AuditRepository, CompanyRepository
)
from helper.tenant import resolve_tenant_context
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
        self.comp_repo = CompanyRepository(db)
        self.audit_repo = AuditRepository(db)
        self.excel_reader = ExcelReaderService()
        self.llm_service = LocalLLMService()
        self.validator = AccountingValidatorService()
        self.tally_client = TallyClientService()

    def ingest_excel_file(self, file_path: str, filename: str) -> ImportBatch:
        # Resolve multi-tenant context
        company_id, fy_id = resolve_tenant_context(self.db)

        # 1. Read file and check hash for duplicates within the active company
        file_hash, file_size, _ = self.excel_reader.read_and_validate_file(file_path)

        existing_batch = self.batch_repo.get_by_file_hash(file_hash, company_id=company_id)
        if existing_batch:
            print("\n" + "=" * 78, flush=True)
            print(f"⚠️ [Duplicate Statement File Detected]", flush=True)
            print(f"📁 File Name      : {filename}", flush=True)
            print(f"📦 Existing Batch : {existing_batch.batch_id} (Imported: {existing_batch.created_at})", flush=True)
            print(f"🛑 Reason         : Re-upload blocked to prevent duplicate General Ledger postings.", flush=True)
            print("=" * 78 + "\n", flush=True)
            self.audit_repo.log(
                action="DUPLICATE_FILE_REJECTED",
                summary=f"File {filename} rejected as duplicate of batch {existing_batch.batch_id}",
                company_id=company_id,
                details={"file_hash": file_hash, "original_batch_id": existing_batch.batch_id}
            )
            raise ValueError(f"Duplicate file detected. This file was previously imported in batch '{existing_batch.batch_id}'.")

        # Resolve company bank ledger
        bank_ledger = (
            self.db.query(LedgerAccount)
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c"))
            )
            .first()
        )
        if not bank_ledger:
            # Auto-seed standard chart of accounts & bank ledger for this company
            self.comp_repo.seed_company_chart_of_accounts(company_id)
            bank_ledger = (
                self.db.query(LedgerAccount)
                .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
                .filter(
                    LedgerAccount.company_id == company_id,
                    AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c"))
                )
                .first()
            )
        if not bank_ledger:
            bank_ledger = self.db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name.ilike("%HDFC%")
            ).first()
        if not bank_ledger:
            bank_ledger = self.db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id
            ).first()

        if not bank_ledger:
            raise ValueError(f"Unable to initialize Bank Ledger for company ID {company_id}.")

        bank_ledger_id = bank_ledger.id

        # 2. Create batch record
        batch_id_str = f"BATCH-{uuid.uuid4().hex[:8].upper()}"
        batch = ImportBatch(
            company_id=company_id,
            fy_id=fy_id,
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
            company_id=company_id,
            batch_id=batch.id
        )

        # 3. Parse transactions from file
        try:
            valid_rows, error_rows = self.excel_reader.parse_bank_statement(file_path)
            batch.total_rows = len(valid_rows) + len(error_rows)
            batch.parsed_rows = len(valid_rows)
            batch.failed_rows = len(error_rows)

            total_valid = len(valid_rows)
            auto_posted_count = 0
            clarification_count = 0

            print("\n" + "=" * 78, flush=True)
            print("🚀 [TallyPilot Ingestion Pipeline] Starting Bank Statement Processing", flush=True)
            print(f"📁 Statement File : {filename} ({file_size} bytes)", flush=True)
            print(f"📦 Batch ID       : {batch_id_str}", flush=True)
            print(f"🤖 Active LLM     : {self.llm_service.active_llm.upper()} (Model: {self.llm_service.model})", flush=True)
            print(f"🎯 Auto Threshold : {self.llm_service.confidence_threshold * 100:.0f}% confidence", flush=True)
            print(f"📑 Statement Rows : {total_valid} valid row(s) to process", flush=True)
            print("=" * 78, flush=True)

            # Available ledgers from master
            ledgers = [l.name for l in self.ledger_repo.list_all()]
            if not ledgers:
                sync_list, _ = self.tally_client.sync_ledgers_from_tally()
                for item in sync_list:
                    self.ledger_repo.upsert(item["name"], item["parent_group"])
                ledgers = [l.name for l in self.ledger_repo.list_all()]

            for idx, row_data in enumerate(valid_rows, 1):
                debit_f = float(row_data["debit_amount"])
                credit_f = float(row_data["credit_amount"])
                amt_str = f"Debit ₹{debit_f:,.2f}" if debit_f > 0 else f"Credit ₹{credit_f:,.2f}"

                print(f"\n[{idx}/{total_valid}] ────────────────────────────────────────────────────────", flush=True)
                print(f"📅 Row #{row_data['source_row_index']} | Date: {row_data['transaction_date']} | {amt_str} | Ref: {row_data.get('bank_reference') or 'N/A'}", flush=True)
                print(f"📄 Narration: \"{row_data['narration']}\"", flush=True)

                tx = BankTransaction(
                    company_id=company_id,
                    batch_id=batch.id,
                    bank_ledger_id=bank_ledger_id,
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
                ai_prop, is_fallback = self.llm_service.classify_transaction(
                    narration=row_data["narration"],
                    debit_amount=debit_f,
                    credit_amount=credit_f,
                    available_ledgers=ledgers
                )

                classification = TransactionClassification(
                    company_id=company_id,
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
                    clarification_count += 1
                    tx.status = TransactionStatus.NEEDS_CLARIFICATION.value
                    tx.requires_review = True
                    self.tx_repo.update(tx)
                    reason = "Confidence < 80%" if ai_prop.confidence < self.llm_service.confidence_threshold else "Accounting validation / human review flag"
                    print(f"   ⚠️ [Pipeline Decision] -> NEEDS CLARIFICATION ({reason})", flush=True)
                    print(f"      Transaction #{tx.id} queued for user review in Clarification Queue.", flush=True)
                else:
                    auto_posted_count += 1
                    tx.status = TransactionStatus.PENDING_APPROVAL.value
                    tx.requires_review = False
                    self.tx_repo.update(tx)
                    print(f"   🎯 [Pipeline Decision] -> HIGH CONFIDENCE ({float(ai_prop.confidence)*100:.1f}%) & VALID", flush=True)
                    print(f"      Auto-approving & posting directly to General Ledger & Tally Prime...", flush=True)
                    try:
                        post_res = self.approve_and_post_transaction(
                            tx.id,
                            ApproveTransactionRequest(
                                approver_user="AUTO_AI",
                                approval_notes=f"Auto-approved & posted (Confidence: {float(ai_prop.confidence)*100:.1f}%)"
                            )
                        )
                        v_num = post_res.get("voucher", {}).get("voucher_number", f"Voucher for Tx #{tx.id}")
                        print(f"      ✅ Posted Successfully! Voucher #{v_num} created in GL.", flush=True)
                    except Exception as auto_err:
                        print(f"      ❌ Auto-post error for Tx #{tx.id}: {auto_err}", flush=True)

            batch.status = "COMPLETED"
            self.batch_repo.update(batch)

            print("\n" + "=" * 78, flush=True)
            print(f"🎉 [Batch Complete] {batch_id_str} | File: {filename}", flush=True)
            print(f"📊 Summary: Total Processed: {total_valid} | Auto-Posted Vouchers: {auto_posted_count} | Needs Clarification: {clarification_count}", flush=True)
            print("=" * 78 + "\n", flush=True)

            self.audit_repo.log(
                action="BATCH_PROCESSED",
                summary=f"Batch {batch_id_str} completed with {batch.parsed_rows} parsed, {batch.failed_rows} failed rows.",
                company_id=company_id,
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
                company_id=company_id,
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
            company_id=tx.company_id,
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
            self.tx_repo.update(tx)

            # Auto-post immediately to official Vouchers & Tally Prime
            try:
                self.approve_and_post_transaction(
                    tx.id,
                    ApproveTransactionRequest(
                        approver_user="finance_user",
                        approval_notes=req.reviewer_notes or "Clarified and auto-posted directly to vouchers"
                    )
                )
                refreshed_tx = self.tx_repo.get_by_id(tx.id)
                if refreshed_tx:
                    tx = refreshed_tx
            except Exception as auto_post_err:
                print(f">> [WorkflowService] Auto-post after clarification error for Tx #{tx.id}: {auto_post_err}")
        else:
            tx.status = TransactionStatus.NEEDS_CLARIFICATION.value
            tx.requires_review = True
            self.tx_repo.update(tx)

        self.audit_repo.log(
            action="TRANSACTION_CLARIFIED",
            summary=f"Transaction #{tx.id} clarified with ledger '{req.selected_ledger}'. New status: {tx.status}",
            company_id=tx.company_id,
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
            company_id=tx.company_id,
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
            company_id=tx.company_id,
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

            # Record and post double-entry voucher in Day Book & General Ledger
            voucher = self.create_book_voucher_for_transaction(
                tx=tx,
                target_ledger=target_ledger,
                voucher_type=voucher_type,
                created_by=req.approver_user or "SYSTEM"
            )

            self.audit_repo.log(
                action="TALLY_VOUCHER_POSTED",
                summary=f"Transaction #{tx.id} successfully posted to Tally Prime (GUID: {tally_res.get('guid')}, Voucher #{getattr(voucher, 'voucher_number', None)})",
                company_id=tx.company_id,
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
                company_id=tx.company_id,
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
            company_id=tx.company_id,
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
            company_id=tx.company_id,
            transaction_id=tx.id,
            previous_status=prev_status,
            new_status=tx.status
        )
        return tx

    def create_book_voucher_for_transaction(self, tx: BankTransaction, target_ledger: str, voucher_type: str, created_by: str = "SYSTEM") -> Optional[Any]:
        """Creates and posts double-entry Voucher & General Ledger entries for a bank transaction."""
        from services.voucher_service import VoucherService
        try:
            # 1. Resolve target ledger account
            target_acc = self.db.query(LedgerAccount).filter(
                LedgerAccount.company_id == tx.company_id,
                LedgerAccount.name == target_ledger
            ).first()
            if not target_acc:
                target_acc = self.db.query(LedgerAccount).filter(
                    LedgerAccount.company_id == tx.company_id,
                    func.lower(LedgerAccount.name) == target_ledger.lower()
                ).first()

            if not target_acc:
                default_group = self.db.query(AccountGroup).filter(
                    AccountGroup.company_id == tx.company_id,
                    AccountGroup.name == ("Direct Expenses" if (tx.debit_amount or 0) > 0 else "Sales Accounts")
                ).first()
                if not default_group:
                    default_group = self.db.query(AccountGroup).filter(
                        AccountGroup.company_id == tx.company_id
                    ).first()
                if not default_group:
                    self.comp_repo.seed_company_chart_of_accounts(tx.company_id)
                    default_group = self.db.query(AccountGroup).filter(
                        AccountGroup.company_id == tx.company_id
                    ).first()

                target_acc = LedgerAccount(
                    company_id=tx.company_id,
                    group_id=default_group.id,
                    name=target_ledger,
                    opening_balance=Decimal("0.00"),
                    current_balance=Decimal("0.00"),
                    is_active=True
                )
                self.db.add(target_acc)
                self.db.flush()

            bank_ledger_id = tx.bank_ledger_id

            # Prevent Debit and Credit having the identical ledger account
            if target_acc.id == bank_ledger_id:
                narration_lower = (tx.narration or "").lower()
                if any(w in narration_lower for w in ["cash", "atm", "wdl"]):
                    cash_acc = self.db.query(LedgerAccount).filter(
                        LedgerAccount.company_id == tx.company_id,
                        LedgerAccount.name.ilike("%cash%")
                    ).first()
                    if cash_acc:
                        target_acc = cash_acc
                        voucher_type = "Contra"
                elif any(w in narration_lower for w in ["sms", "chg", "charge", "fee"]):
                    chg_acc = self.db.query(LedgerAccount).filter(
                        LedgerAccount.company_id == tx.company_id,
                        LedgerAccount.name.ilike("%bank charge%")
                    ).first()
                    if chg_acc:
                        target_acc = chg_acc
                        voucher_type = "Payment"

            # Double-entry lines:
            # If Bank Debit (Payment/Expense): Target Dr, Bank Cr
            # If Bank Credit (Deposit/Receipt): Bank Dr, Target Cr
            dr_amt = Decimal(str(tx.debit_amount or 0))
            cr_amt = Decimal(str(tx.credit_amount or 0))
            if dr_amt > 0:
                lines_data = [
                    {"ledger_id": target_acc.id, "debit_amount": dr_amt, "credit_amount": Decimal("0.00"), "narration": tx.narration},
                    {"ledger_id": bank_ledger_id, "debit_amount": Decimal("0.00"), "credit_amount": dr_amt, "narration": tx.narration}
                ]
            else:
                lines_data = [
                    {"ledger_id": bank_ledger_id, "debit_amount": cr_amt, "credit_amount": Decimal("0.00"), "narration": tx.narration},
                    {"ledger_id": target_acc.id, "debit_amount": Decimal("0.00"), "credit_amount": cr_amt, "narration": tx.narration}
                ]

            voucher = VoucherService.create_voucher(
                db=self.db,
                company_id=tx.company_id,
                voucher_type=voucher_type,
                voucher_date=tx.transaction_date,
                narration=tx.narration,
                lines_data=lines_data,
                bank_transaction_id=tx.id,
                created_by=created_by,
                auto_post=True
            )
            tx.matched_voucher_id = voucher.id
            tx.reconciliation_status = "RECONCILED"
            self.tx_repo.update(tx)
            self.db.commit()
            return voucher
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[WorkflowService] Warning: Could not create book voucher for tx #{tx.id}: {e}")
            return None



