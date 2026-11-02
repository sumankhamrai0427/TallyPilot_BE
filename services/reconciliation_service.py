"""Bank Reconciliation Engine (HLA Part 11).
Implements automated matching between bank statement feeds and General Ledger vouchers,
duplicate transaction detection, and BRS date variance analysis.
"""
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from model.models import (
    BankTransaction, Voucher, VoucherLine, LedgerAccount,
    AccountGroup, BankReconciliation, BankReconciliationItem,
    ReconciliationStatus, ReconciliationMatchType, ReconciliationMatchStatus,
    AuditLog
)
from utils.logger import logger


class ReconciliationService:

    @classmethod
    def detect_duplicates(cls, db: Session, company_id: int) -> int:
        """Identifies duplicate bank transactions sharing identical bank references or amounts + dates."""
        duplicates_count = 0

        # 1. Duplicates by bank_reference
        ref_dups = (
            db.query(BankTransaction.bank_reference)
            .filter(
                BankTransaction.company_id == company_id,
                BankTransaction.bank_reference.isnot(None),
                BankTransaction.bank_reference != ""
            )
            .group_by(BankTransaction.bank_reference)
            .having(func.count(BankTransaction.id) > 1)
            .all()
        )

        for (ref,) in ref_dups:
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.bank_reference == ref
                )
                .order_by(BankTransaction.id.asc())
                .all()
            )
            # Mark second and subsequent transactions as duplicates
            for tx in txs[1:]:
                if not tx.is_duplicate:
                    tx.is_duplicate = True
                    duplicates_count += 1

        # 2. Duplicates by date, amount, and narration
        content_dups = (
            db.query(
                BankTransaction.transaction_date,
                BankTransaction.debit_amount,
                BankTransaction.credit_amount,
                BankTransaction.narration
            )
            .filter(BankTransaction.company_id == company_id)
            .group_by(
                BankTransaction.transaction_date,
                BankTransaction.debit_amount,
                BankTransaction.credit_amount,
                BankTransaction.narration
            )
            .having(func.count(BankTransaction.id) > 1)
            .all()
        )

        for t_date, dr, cr, narr in content_dups:
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.transaction_date == t_date,
                    BankTransaction.debit_amount == dr,
                    BankTransaction.credit_amount == cr,
                    BankTransaction.narration == narr
                )
                .order_by(BankTransaction.id.asc())
                .all()
            )
            for tx in txs[1:]:
                if not tx.is_duplicate:
                    tx.is_duplicate = True
                    duplicates_count += 1

        db.flush()
        return duplicates_count

    @classmethod
    def auto_reconcile_with_books(cls, db: Session, company_id: int) -> Dict[str, int]:
        """HLA Part 11: Checks whether payment/receipt has already been recorded in Books

        before proposing duplicate vouchers, and links them automatically.
        """
        # First detect duplicates
        duplicates_flagged = cls.detect_duplicates(db, company_id)

        # Find bank ledgers for company
        bank_ledgers = (
            db.query(LedgerAccount.id)
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c"))
            )
            .all()
        )
        bank_ledger_ids = [bl[0] for bl in bank_ledgers]

        if not bank_ledger_ids:
            return {"matched_count": 0, "duplicates_flagged": duplicates_flagged}

        # Fetch unreconciled bank transactions
        unreconciled_txs = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.company_id == company_id,
                BankTransaction.reconciliation_status != "RECONCILED",
                BankTransaction.is_duplicate == False
            )
            .all()
        )

        matched_count = 0

        for tx in unreconciled_txs:
            amount = tx.amount
            is_debit = (tx.debit_amount or 0) > 0

            # Find matching posted voucher line in books on the bank account
            # In double entry:
            # - Bank Debit (withdrawal) -> Book Credit on Bank Account
            # - Bank Credit (deposit)   -> Book Debit on Bank Account
            target_col = VoucherLine.credit_amount if is_debit else VoucherLine.debit_amount

            # 1. Match by Bank Reference / Cheque Number
            matched_line = None
            if tx.bank_reference or tx.cheque_number:
                ref_terms = [t for t in [tx.bank_reference, tx.cheque_number] if t]
                query = (
                    db.query(VoucherLine, Voucher)
                    .join(Voucher, Voucher.id == VoucherLine.voucher_id)
                    .filter(
                        VoucherLine.company_id == company_id,
                        VoucherLine.ledger_id.in_(bank_ledger_ids),
                        target_col == amount,
                        Voucher.status == "POSTED"
                    )
                )
                conditions = []
                for term in ref_terms:
                    conditions.append(Voucher.narration.ilike(f"%{term}%"))
                    conditions.append(VoucherLine.narration.ilike(f"%{term}%"))
                query = query.filter(or_(*conditions))
                matched_pair = query.first()
                if matched_pair:
                    matched_line, matched_voucher = matched_pair

            # 2. Match by exact Amount within date window (±5 days) if not matched by ref
            if not matched_line:
                start_date = tx.transaction_date - timedelta(days=5)
                end_date = tx.transaction_date + timedelta(days=5)

                matched_pair = (
                    db.query(VoucherLine, Voucher)
                    .join(Voucher, Voucher.id == VoucherLine.voucher_id)
                    .filter(
                        VoucherLine.company_id == company_id,
                        VoucherLine.ledger_id.in_(bank_ledger_ids),
                        target_col == amount,
                        Voucher.status == "POSTED",
                        Voucher.voucher_date >= start_date,
                        Voucher.voucher_date <= end_date,
                        # Not already linked to another bank transaction
                        Voucher.bank_transaction_id.is_(None)
                    )
                    .first()
                )
                if matched_pair:
                    matched_line, matched_voucher = matched_pair

            # If match found, reconcile!
            if matched_line and matched_voucher:
                tx.reconciliation_status = "RECONCILED"
                tx.matched_voucher_id = matched_voucher.id
                tx.clearance_date = tx.transaction_date
                tx.status = "PROCESSED"

                # Link voucher back
                matched_voucher.bank_transaction_id = tx.id

                # Record audit log
                audit = AuditLog(
                    company_id=company_id,
                    timestamp=datetime.utcnow(),
                    actor="AUTO_RECON_ENGINE",
                    action="TRANSACTION_RECONCILED",
                    transaction_id=tx.id,
                    new_status="RECONCILED",
                    summary=f"Bank Tx #{tx.id} automatically matched to existing Voucher {matched_voucher.voucher_number}"
                )
                db.add(audit)
                matched_count += 1

        db.commit()
        return {
            "matched_count": matched_count,
            "duplicates_flagged": duplicates_flagged
        }

