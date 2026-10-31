"""Bank Reconciliation controller.
Handles multi-tenant bank reconciliation, transaction-voucher line matching, and discrepancy reporting.
"""
from datetime import datetime, date
from decimal import Decimal
from flask import jsonify, request
from sqlalchemy import func
from database.dbConnection import SessionLocal
from helper.tenant import resolve_tenant_context
from model.models import (
    BankTransaction, VoucherLine, BankReconciliation, 
    BankReconciliationItem, LedgerAccount, GeneralLedger,
    AccountGroup
)
from utils.logger import logger


def get_reconciliation_summary():
    """Returns bank reconciliation metrics, balances, and unreconciled counts."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)

        # 1. Bank transaction recon statuses
        status_counts = (
            db.query(BankTransaction.reconciliation_status, func.count(BankTransaction.id))
            .filter(BankTransaction.company_id == company_id)
            .group_by(BankTransaction.reconciliation_status)
            .all()
        )
        recon_map = {status: count for status, count in status_counts}

        # 2. Bank accounts book balances
        bank_ledgers = (
            db.query(LedgerAccount)
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c"))
            )
            .all()
        )

        accounts_summary = []
        for bl in bank_ledgers:
            # GL sum for this bank ledger
            gl_totals = (
                db.query(
                    func.sum(GeneralLedger.debit_amount).label("total_dr"),
                    func.sum(GeneralLedger.credit_amount).label("total_cr")
                )
                .filter(GeneralLedger.company_id == company_id, GeneralLedger.ledger_id == bl.id)
                .first()
            )
            total_dr = Decimal(str(gl_totals.total_dr or 0)) if gl_totals else Decimal("0.00")
            total_cr = Decimal(str(gl_totals.total_cr or 0)) if gl_totals else Decimal("0.00")
            book_balance = bl.opening_balance + total_dr - total_cr

            accounts_summary.append({
                "ledger_id": bl.id,
                "ledger_name": bl.name,
                "opening_balance": float(bl.opening_balance),
                "book_balance": float(book_balance),
                "current_balance": float(bl.current_balance)
            })

        return jsonify({
            "company_id": company_id,
            "reconciled_transactions": recon_map.get("RECONCILED", 0),
            "unreconciled_transactions": recon_map.get("UNRECONCILED", 0),
            "partially_reconciled": recon_map.get("PARTIALLY_RECONCILED", 0),
            "bank_accounts": accounts_summary
        }), 200
    except Exception as e:
        logger.error(f"Error fetching reconciliation summary: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def list_unmatched_items():
    """Lists unreconciled bank transactions alongside open voucher lines for side-by-side reconciliation."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)

        # Unreconciled bank transactions
        transactions = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.company_id == company_id,
                BankTransaction.reconciliation_status != "RECONCILED"
            )
            .order_by(BankTransaction.transaction_date.desc())
            .all()
        )

        # Find bank ledgers to get bank voucher lines
        bank_ledger_ids = [
            l.id for l in (
                db.query(LedgerAccount.id)
                .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
                .filter(
                    LedgerAccount.company_id == company_id,
                    AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c"))
                )
                .all()
            )
        ]

        # Voucher lines on bank accounts not fully matched
        voucher_lines = (
            db.query(VoucherLine)
            .filter(
                VoucherLine.company_id == company_id,
                VoucherLine.ledger_id.in_(bank_ledger_ids)
            )
            .order_by(VoucherLine.id.desc())
            .limit(50)
            .all()
        ) if bank_ledger_ids else []

        return jsonify({
            "bank_transactions": [
                {
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "narration": t.narration,
                    "amount": float(t.amount),
                    "transaction_type": t.transaction_type,
                    "bank_reference": t.bank_reference,
                    "suggested_ledger": t.suggested_ledger,
                    "reconciliation_status": t.reconciliation_status
                }
                for t in transactions
            ],
            "voucher_lines": [
                {
                    "id": vl.id,
                    "voucher_id": vl.voucher_id,
                    "voucher_number": vl.voucher.voucher_number if vl.voucher else None,
                    "voucher_date": vl.voucher.voucher_date.isoformat() if vl.voucher else None,
                    "voucher_type": vl.voucher.voucher_type.value if vl.voucher and hasattr(vl.voucher.voucher_type, "value") else str(vl.voucher.voucher_type),
                    "ledger_id": vl.ledger_id,
                    "ledger_name": vl.ledger.name if vl.ledger else None,
                    "debit_amount": float(vl.debit_amount),
                    "credit_amount": float(vl.credit_amount),
                    "narration": vl.narration
                }
                for vl in voucher_lines
            ]
        }), 200
    except Exception as e:
        logger.error(f"Error listing unmatched reconciliation items: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def match_transaction():
    """Manually links a bank transaction with a voucher line and marks it reconciled."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        data = request.get_json() or {}
        tx_id = data.get("transaction_id")
        line_id = data.get("voucher_line_id")

        if not tx_id or not line_id:
            return jsonify({"detail": "transaction_id and voucher_line_id are required"}), 400

        tx = db.query(BankTransaction).filter(
            BankTransaction.id == tx_id,
            BankTransaction.company_id == company_id
        ).first()

        vl = db.query(VoucherLine).filter(
            VoucherLine.id == line_id,
            VoucherLine.company_id == company_id
        ).first()

        if not tx or not vl:
            return jsonify({"detail": "Transaction or Voucher line not found"}), 404

        # Mark transaction reconciled
        tx.reconciliation_status = "RECONCILED"
        tx.status = "PROCESSED"
        
        # Link voucher to transaction if not already linked
        if vl.voucher and not vl.voucher.bank_transaction_id:
            vl.voucher.bank_transaction_id = tx.id

        db.commit()

        return jsonify({
            "message": "Transaction successfully matched and marked RECONCILED",
            "transaction_id": tx.id,
            "reconciliation_status": tx.reconciliation_status
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error matching reconciliation item: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()
