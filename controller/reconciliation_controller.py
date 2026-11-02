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


def run_auto_reconcile():
    """HLA Part 11: Runs automated reconciliation and duplicate detection."""
    db = SessionLocal()
    try:
        from services.reconciliation_service import ReconciliationService
        company_id, _ = resolve_tenant_context(db)
        result = ReconciliationService.auto_reconcile_with_books(db, company_id)
        return jsonify({
            "message": f"Auto-reconciliation complete: {result['matched_count']} entries matched, {result['duplicates_flagged']} duplicates detected",
            "matched_count": result["matched_count"],
            "duplicates_flagged": result["duplicates_flagged"]
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error running auto-reconciliation: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_reconciliation_views():
    """HLA Part 11: Structured views for Matched, Unmatched Bank, Unmatched Books, Duplicates, and Date Differences."""
    db = SessionLocal()
    try:
        from model.models import Voucher
        company_id, _ = resolve_tenant_context(db)
        view = request.args.get("view", "matched")
        today = date.today()

        # Find bank ledger IDs
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

        if view == "matched":
            # Reconciled bank transactions with linked vouchers
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.reconciliation_status == "RECONCILED"
                )
                .order_by(BankTransaction.transaction_date.desc())
                .all()
            )
            results = []
            for t in txs:
                # Find linked voucher
                v = t.matched_voucher
                if not v and t.id:
                    v = db.query(Voucher).filter(Voucher.bank_transaction_id == t.id).first()

                clearance_dt = t.clearance_date or t.transaction_date
                v_date = v.voucher_date if v else None
                lag = (clearance_dt - v_date).days if (clearance_dt and v_date) else 0

                results.append({
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "clearance_date": clearance_dt.isoformat() if clearance_dt else None,
                    "bank_reference": t.bank_reference,
                    "narration": t.narration,
                    "amount": float(t.amount),
                    "transaction_type": t.transaction_type,
                    "voucher_id": v.id if v else None,
                    "voucher_number": v.voucher_number if v else "—",
                    "voucher_type": v.voucher_type.value if (v and hasattr(v.voucher_type, "value")) else (str(v.voucher_type) if v else None),
                    "voucher_date": v_date.isoformat() if v_date else None,
                    "lag_days": lag
                })
            return jsonify({"items": results, "total": len(results)}), 200

        elif view == "unmatched_bank":
            # Bank transactions without corresponding books voucher
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.reconciliation_status != "RECONCILED",
                    BankTransaction.is_duplicate == False
                )
                .order_by(BankTransaction.transaction_date.desc())
                .all()
            )
            results = [
                {
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "bank_reference": t.bank_reference,
                    "narration": t.narration,
                    "amount": float(t.amount),
                    "transaction_type": t.transaction_type,
                    "suggested_ledger": t.suggested_ledger,
                    "suggested_voucher_type": t.classification.suggested_voucher_type if t.classification else ("Payment" if t.transaction_type == "DEBIT" else "Receipt"),
                    "status": t.status
                }
                for t in txs
            ]
            return jsonify({"items": results, "total": len(results)}), 200

        elif view == "unmatched_books":
            # Book vouchers on bank accounts not cleared in the bank
            v_lines = (
                db.query(VoucherLine, Voucher)
                .join(Voucher, Voucher.id == VoucherLine.voucher_id)
                .filter(
                    VoucherLine.company_id == company_id,
                    VoucherLine.ledger_id.in_(bank_ledger_ids) if bank_ledger_ids else True,
                    Voucher.status == "POSTED",
                    Voucher.bank_transaction_id.is_(None)
                )
                .order_by(Voucher.voucher_date.desc())
                .all()
            )
            results = []
            for vl, v in v_lines:
                v_dt = v.voucher_date
                age_days = (today - v_dt).days if v_dt else 0
                amount = float(vl.credit_amount) if vl.credit_amount > 0 else float(vl.debit_amount)
                nature = "ISSUE (Payment)" if vl.credit_amount > 0 else "DEPOSIT (Receipt)"
                results.append({
                    "voucher_id": v.id,
                    "voucher_line_id": vl.id,
                    "voucher_number": v.voucher_number,
                    "voucher_date": v_dt.isoformat(),
                    "voucher_type": v.voucher_type.value if hasattr(v.voucher_type, "value") else str(v.voucher_type),
                    "ledger_name": vl.ledger.name if vl.ledger else "Bank",
                    "amount": amount,
                    "nature": nature,
                    "narration": vl.narration or v.narration,
                    "age_days": age_days
                })
            return jsonify({"items": results, "total": len(results)}), 200

        elif view == "duplicates":
            # Duplicate transactions
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.is_duplicate == True
                )
                .order_by(BankTransaction.transaction_date.desc())
                .all()
            )
            results = [
                {
                    "id": t.id,
                    "date": t.transaction_date.isoformat(),
                    "bank_reference": t.bank_reference,
                    "narration": t.narration,
                    "amount": float(t.amount),
                    "transaction_type": t.transaction_type,
                    "flag_reason": "Duplicate bank reference or duplicate amount & date detected"
                }
                for t in txs
            ]
            return jsonify({"items": results, "total": len(results)}), 200

        elif view == "date_differences":
            # Reconciled items where Clearance Date != Voucher Date
            txs = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.company_id == company_id,
                    BankTransaction.reconciliation_status == "RECONCILED"
                )
                .all()
            )
            results = []
            for t in txs:
                v = t.matched_voucher
                if not v and t.id:
                    v = db.query(Voucher).filter(Voucher.bank_transaction_id == t.id).first()

                clearance_dt = t.clearance_date or t.transaction_date
                v_date = v.voucher_date if v else None
                if clearance_dt and v_date and clearance_dt != v_date:
                    lag = (clearance_dt - v_date).days
                    results.append({
                        "id": t.id,
                        "bank_reference": t.bank_reference,
                        "narration": t.narration,
                        "amount": float(t.amount),
                        "transaction_type": t.transaction_type,
                        "voucher_number": v.voucher_number if v else "—",
                        "voucher_date": v_date.isoformat(),
                        "clearance_date": clearance_dt.isoformat(),
                        "lag_days": lag,
                        "lag_description": f"{abs(lag)} days {'delay in bank clearing' if lag > 0 else 'prior bank debit'}"
                    })
            results.sort(key=lambda x: abs(x["lag_days"]), reverse=True)
            return jsonify({"items": results, "total": len(results)}), 200

        return jsonify({"detail": f"Unknown view {view}"}), 400
    except Exception as e:
        logger.error(f"Error fetching reconciliation view {request.args.get('view')}: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()

