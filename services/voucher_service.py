"""Double-Entry Accounting & Voucher Posting Engine.
Implements atomic voucher posting, debit/credit balancing guards, and General Ledger posting.
"""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from model.models import (
    Voucher, VoucherLine, GeneralLedger, VoucherStatus, 
    VoucherType, BankTransaction, LedgerAccount, FinancialYear,
    AuditLog, Party
)
from utils.logger import logger


class VoucherService:

    @staticmethod
    def get_or_resolve_financial_year(db: Session, company_id: int, voucher_date) -> FinancialYear:
        """Resolves the financial year covering the given date, or active current financial year."""
        fy = db.query(FinancialYear).filter(
            FinancialYear.company_id == company_id,
            FinancialYear.start_date <= voucher_date,
            FinancialYear.end_date >= voucher_date
        ).first()

        if not fy:
            fy = db.query(FinancialYear).filter(
                FinancialYear.company_id == company_id,
                FinancialYear.is_current == 1
            ).first()

        if not fy:
            raise ValueError(f"No active or matching Financial Year found for company_id={company_id}")
        return fy

    @staticmethod
    def generate_voucher_number(db: Session, company_id: int, fy_id: int, voucher_type: str) -> str:
        """Generates a sequential human-readable voucher number scoped to company and FY."""
        prefix_map = {
            "Payment": "PV",
            "Receipt": "RV",
            "Contra": "CV",
            "Journal": "JV",
            "Sales": "SV",
            "Purchase": "PUR"
        }
        prefix = prefix_map.get(voucher_type, "VCH")
        count = db.query(func.count(Voucher.id)).filter(
            Voucher.company_id == company_id,
            Voucher.fy_id == fy_id,
            Voucher.voucher_type == voucher_type
        ).scalar() or 0
        return f"{prefix}-{count + 1:04d}"

    @classmethod
    def create_voucher(
        cls,
        db: Session,
        company_id: int,
        voucher_type: str,
        voucher_date,
        narration: str,
        lines_data: List[dict],
        bank_transaction_id: Optional[int] = None,
        source_document_id: Optional[int] = None,
        created_by: str = "SYSTEM",
        auto_post: bool = False
    ) -> Voucher:
        """Creates a double-entry voucher with balanced lines. Optionally posts immediately."""
        fy = cls.get_or_resolve_financial_year(db, company_id, voucher_date)

        # Validate that date is within financial year
        if voucher_date < fy.start_date or voucher_date > fy.end_date:
            raise ValueError(f"Voucher date {voucher_date} is outside Financial Year ({fy.start_date} to {fy.end_date})")

        # Validate Debit == Credit
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        for line in lines_data:
            dr = Decimal(str(line.get("debit_amount", 0)))
            cr = Decimal(str(line.get("credit_amount", 0)))
            if dr < 0 or cr < 0:
                raise ValueError("Line amounts cannot be negative.")
            if dr > 0 and cr > 0:
                raise ValueError("A single line cannot have both positive debit and credit.")
            if dr == 0 and cr == 0:
                raise ValueError("Line must have a non-zero debit or credit amount.")
            total_debit += dr
            total_credit += cr

        if total_debit != total_credit:
            raise ValueError(
                f"Double-entry out of balance! Total Debit: {total_debit} does not equal Total Credit: {total_credit}"
            )

        voucher_num = cls.generate_voucher_number(db, company_id, fy.id, voucher_type)

        voucher = Voucher(
            company_id=company_id,
            fy_id=fy.id,
            voucher_number=voucher_num,
            voucher_type=voucher_type,
            voucher_date=voucher_date,
            total_amount=total_debit,
            narration=narration,
            bank_transaction_id=bank_transaction_id,
            source_document_id=source_document_id,
            status=VoucherStatus.DRAFT.value,
            created_by=created_by,
            created_at=datetime.utcnow()
        )
        db.add(voucher)
        db.flush()

        # Add lines
        for idx, line in enumerate(lines_data, start=1):
            ledger_id = line["ledger_id"]
            party_id = line.get("party_id")

            # Validate ledger belongs to same company
            ledger = db.query(LedgerAccount).filter(
                LedgerAccount.id == ledger_id,
                LedgerAccount.company_id == company_id
            ).first()
            if not ledger:
                raise ValueError(f"Ledger ID {ledger_id} not found in company {company_id}")

            # If party_id provided, validate party matches ledger
            if party_id:
                party = db.query(Party).filter(
                    Party.id == party_id,
                    Party.company_id == company_id,
                    Party.ledger_id == ledger_id
                ).first()
                if not party:
                    raise ValueError(f"Party ID {party_id} does not match Ledger ID {ledger_id}")

            vl = VoucherLine(
                company_id=company_id,
                voucher_id=voucher.id,
                line_number=idx,
                ledger_id=ledger_id,
                party_id=party_id,
                debit_amount=Decimal(str(line.get("debit_amount", 0))),
                credit_amount=Decimal(str(line.get("credit_amount", 0))),
                narration=line.get("narration") or narration,
                created_at=datetime.utcnow()
            )
            db.add(vl)

        db.flush()

        if auto_post:
            cls.post_voucher(db, voucher.id, company_id)

        return voucher

    @classmethod
    def post_voucher(cls, db: Session, voucher_id: int, company_id: int) -> Voucher:
        """Atomically posts an approved voucher to the General Ledger and updates ledger balances."""
        voucher = db.query(Voucher).filter(
            Voucher.id == voucher_id,
            Voucher.company_id == company_id
        ).first()

        if not voucher:
            raise ValueError(f"Voucher ID {voucher_id} not found")

        if voucher.status == VoucherStatus.POSTED.value:
            raise ValueError("Voucher is already posted.")

        if voucher.status in (VoucherStatus.REVERSED.value, VoucherStatus.CANCELLED.value):
            raise ValueError(f"Cannot post voucher in {voucher.status} status.")

        # Ensure lines are loaded
        lines = db.query(VoucherLine).filter(
            VoucherLine.voucher_id == voucher.id,
            VoucherLine.company_id == company_id
        ).all()

        total_dr = sum(l.debit_amount for l in lines)
        total_cr = sum(l.credit_amount for l in lines)

        if total_dr != total_cr or total_dr == 0:
            raise ValueError(f"Cannot post unbalanced voucher: Dr={total_dr}, Cr={total_cr}")

        # Post each line into general_ledger
        for line in lines:
            gl = GeneralLedger(
                company_id=company_id,
                fy_id=voucher.fy_id,
                voucher_id=voucher.id,
                voucher_line_id=line.id,
                posting_date=voucher.voucher_date,
                ledger_id=line.ledger_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                running_balance=Decimal("0.00"),
                is_reversed=False,
                created_at=datetime.utcnow()
            )
            db.add(gl)

            # Update account current_balance
            ledger = db.query(LedgerAccount).filter(LedgerAccount.id == line.ledger_id).first()
            if ledger:
                ledger.current_balance = (ledger.current_balance or Decimal("0.00")) + line.debit_amount - line.credit_amount

        voucher.status = VoucherStatus.POSTED.value
        voucher.posted_at = datetime.utcnow()

        # If linked to a bank transaction, mark reconciled
        if voucher.bank_transaction_id:
            bt = db.query(BankTransaction).filter(
                BankTransaction.id == voucher.bank_transaction_id,
                BankTransaction.company_id == company_id
            ).first()
            if bt:
                bt.status = "PROCESSED"
                bt.reconciliation_status = "RECONCILED"

        # Record audit log
        audit = AuditLog(
            company_id=company_id,
            timestamp=datetime.utcnow(),
            actor="SYSTEM",
            action="VOUCHER_POSTED",
            transaction_id=voucher.bank_transaction_id,
            new_status="POSTED",
            summary=f"Voucher {voucher.voucher_number} posted to General Ledger (Amount: {voucher.total_amount})"
        )
        db.add(audit)
        db.flush()
        return voucher

