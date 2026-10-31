"""Vouchers and Double-Entry General Ledger controller.
Enforces multi-tenancy, balancing constraints, and accounting validation.
"""
from datetime import datetime, date
from decimal import Decimal
from flask import jsonify, request
from database.dbConnection import SessionLocal
from database.repositories import VoucherRepository, TransactionRepository, LedgerRepository
from helper.tenant import resolve_tenant_context
from services.voucher_service import VoucherService
from model.models import (
    Voucher, VoucherLine, BankTransaction, LedgerAccount, 
    VoucherStatus, VoucherType, GeneralLedger, AccountGroup
)
from utils.logger import logger


def list_vouchers():
    """Lists double-entry vouchers with pagination, type, and status filtering."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        repo = VoucherRepository(db)

        page = int(request.args.get("page", 1))
        limit = min(int(request.args.get("limit", 20)), 100)
        skip = (page - 1) * limit
        voucher_type = request.args.get("voucher_type")
        status = request.args.get("status")
        search = request.args.get("search")

        vouchers, total = repo.list_vouchers(
            company_id=company_id,
            fy_id=fy_id,
            voucher_type=voucher_type,
            status=status,
            search=search,
            skip=skip,
            limit=limit
        )

        results = []
        for v in vouchers:
            results.append({
                "id": v.id,
                "company_id": v.company_id,
                "fy_id": v.fy_id,
                "voucher_number": v.voucher_number,
                "voucher_type": v.voucher_type.value if hasattr(v.voucher_type, "value") else str(v.voucher_type),
                "voucher_date": v.voucher_date.isoformat(),
                "total_amount": float(v.total_amount),
                "narration": v.narration,
                "bank_transaction_id": v.bank_transaction_id,
                "status": v.status.value if hasattr(v.status, "value") else str(v.status),
                "created_by": v.created_by,
                "posted_at": v.posted_at.isoformat() if v.posted_at else None,
                "lines_count": len(v.lines),
                "lines": [
                    {
                        "id": l.id,
                        "line_number": l.line_number,
                        "ledger_id": l.ledger_id,
                        "ledger_name": l.ledger.name if l.ledger else None,
                        "party_id": l.party_id,
                        "party_name": (l.party.ledger.name if l.party and l.party.ledger else None),
                        "debit_amount": float(l.debit_amount),
                        "credit_amount": float(l.credit_amount),
                        "narration": l.narration
                    }
                    for l in v.lines
                ]
            })

        return jsonify({
            "items": results,
            "total": total,
            "page": page,
            "limit": limit
        }), 200
    except Exception as e:
        logger.error(f"Error listing vouchers: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_voucher(voucher_id: int):
    """Retrieves full details of a single voucher."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = VoucherRepository(db)
        v = repo.get_voucher_by_id(voucher_id, company_id)

        if not v:
            return jsonify({"detail": "Voucher not found"}), 404

        return jsonify({
            "id": v.id,
            "company_id": v.company_id,
            "fy_id": v.fy_id,
            "voucher_number": v.voucher_number,
            "voucher_type": v.voucher_type.value if hasattr(v.voucher_type, "value") else str(v.voucher_type),
            "voucher_date": v.voucher_date.isoformat(),
            "total_amount": float(v.total_amount),
            "narration": v.narration,
            "bank_transaction_id": v.bank_transaction_id,
            "status": v.status.value if hasattr(v.status, "value") else str(v.status),
            "created_by": v.created_by,
            "posted_at": v.posted_at.isoformat() if v.posted_at else None,
            "created_at": v.created_at.isoformat(),
            "lines": [
                {
                    "id": l.id,
                    "line_number": l.line_number,
                    "ledger_id": l.ledger_id,
                    "ledger_name": l.ledger.name if l.ledger else None,
                    "party_id": l.party_id,
                    "party_name": (l.party.ledger.name if l.party and l.party.ledger else None),
                    "debit_amount": float(l.debit_amount),
                    "credit_amount": float(l.credit_amount),
                    "narration": l.narration
                }
                for l in v.lines
            ],
            "approvals": [
                {
                    "id": a.id,
                    "action": a.action.value if hasattr(a.action, "value") else str(a.action),
                    "approver_role": a.approver_role,
                    "comments": a.comments,
                    "created_at": a.created_at.isoformat()
                }
                for a in v.approvals
            ]
        }), 200
    except Exception as e:
        logger.error(f"Error getting voucher {voucher_id}: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def create_voucher():
    """Creates a new double-entry voucher."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        payload = request.get_json() or {}

        voucher_type = payload.get("voucher_type")
        raw_date = payload.get("voucher_date")
        narration = payload.get("narration", "")
        lines = payload.get("lines", [])
        auto_post = bool(payload.get("auto_post", False))

        if not voucher_type or not raw_date or not lines:
            return jsonify({"detail": "voucher_type, voucher_date, and lines are required"}), 400

        voucher_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if isinstance(raw_date, str) else raw_date

        voucher = VoucherService.create_voucher(
            db=db,
            company_id=company_id,
            voucher_type=voucher_type,
            voucher_date=voucher_date,
            narration=narration,
            lines_data=lines,
            bank_transaction_id=payload.get("bank_transaction_id"),
            source_document_id=payload.get("source_document_id"),
            created_by=payload.get("created_by", "USER"),
            auto_post=auto_post
        )
        db.commit()

        return jsonify({
            "message": "Voucher created successfully",
            "voucher_id": voucher.id,
            "voucher_number": voucher.voucher_number,
            "status": voucher.status
        }), 201
    except ValueError as ve:
        db.rollback()
        return jsonify({"detail": str(ve)}), 400
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating voucher: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def post_voucher(voucher_id: int):
    """Posts a voucher directly to the General Ledger."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        voucher = VoucherService.post_voucher(db, voucher_id, company_id)
        db.commit()

        return jsonify({
            "message": f"Voucher {voucher.voucher_number} posted successfully to General Ledger",
            "voucher_id": voucher.id,
            "status": voucher.status,
            "posted_at": voucher.posted_at.isoformat()
        }), 200
    except ValueError as ve:
        db.rollback()
        return jsonify({"detail": str(ve)}), 400
    except Exception as e:
        db.rollback()
        logger.error(f"Error posting voucher {voucher_id}: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def generate_voucher_from_transaction(tx_id: int):
    """Automatically generates and posts a balanced double-entry voucher from a classified bank transaction."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        tx = db.query(BankTransaction).filter(
            BankTransaction.id == tx_id,
            BankTransaction.company_id == company_id
        ).first()

        if not tx:
            return jsonify({"detail": "Transaction not found"}), 404

        # Check if already has a voucher
        existing = db.query(Voucher).filter(
            Voucher.bank_transaction_id == tx.id,
            Voucher.company_id == company_id
        ).first()
        if existing:
            return jsonify({
                "message": "Voucher already exists for this transaction",
                "voucher_id": existing.id,
                "voucher_number": existing.voucher_number
            }), 200

        # Find bank ledger for company (from Bank Accounts group or name)
        from model.models import AccountGroup
        bank_ledger = (
            db.query(LedgerAccount)
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.name == "Bank Accounts"
            )
            .first()
        )

        if not bank_ledger:
            bank_ledger = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name.ilike("%HDFC%")
            ).first()

        if not bank_ledger:
            return jsonify({"detail": "No bank ledger found for this company"}), 400

        # Determine target ledger from classification or suggested ledger
        suggested_name = tx.suggested_ledger
        target_ledger = None
        if suggested_name:
            target_ledger = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name == suggested_name
            ).first()

        if not target_ledger:
            # Fallback: Suspense Account or General Expense
            target_ledger = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name.ilike("%Suspense%")
            ).first()

        if not target_ledger:
            # Use any non-bank ledger
            target_ledger = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.id != bank_ledger.id
            ).first()

        amount = Decimal(str(tx.amount))

        if tx.transaction_type == "DEBIT":
            voucher_type = "Payment" if target_ledger.name != "Cash" else "Contra"
            lines = [
                {
                    "ledger_id": target_ledger.id,
                    "debit_amount": amount,
                    "credit_amount": Decimal("0.00"),
                    "narration": tx.narration
                },
                {
                    "ledger_id": bank_ledger.id,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": amount,
                    "narration": f"Payment via {bank_ledger.name}"
                }
            ]
        else:
            voucher_type = "Receipt" if target_ledger.name != "Cash" else "Contra"
            lines = [
                {
                    "ledger_id": bank_ledger.id,
                    "debit_amount": amount,
                    "credit_amount": Decimal("0.00"),
                    "narration": f"Receipt into {bank_ledger.name}"
                },
                {
                    "ledger_id": target_ledger.id,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": amount,
                    "narration": tx.narration
                }
            ]

        voucher = VoucherService.create_voucher(
            db=db,
            company_id=company_id,
            voucher_type=voucher_type,
            voucher_date=tx.transaction_date,
            narration=f"{voucher_type} for bank ref: {tx.bank_reference or tx.narration}",
            lines_data=lines,
            bank_transaction_id=tx.id,
            created_by="AUTO_PROCESSOR",
            auto_post=True
        )
        db.commit()

        return jsonify({
            "message": f"Successfully created and posted {voucher_type} voucher",
            "voucher_id": voucher.id,
            "voucher_number": voucher.voucher_number,
            "status": voucher.status
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"Error generating voucher from transaction {tx_id}: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_general_ledger_entries():
    """Lists general ledger postings with ledger, date range, and voucher filtering."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = VoucherRepository(db)

        page = int(request.args.get("page", 1))
        limit = min(int(request.args.get("limit", 50)), 200)
        skip = (page - 1) * limit

        ledger_id = request.args.get("ledger_id", type=int)
        voucher_id = request.args.get("voucher_id", type=int)
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        entries, total = repo.get_gl_entries(
            company_id=company_id,
            ledger_id=ledger_id,
            voucher_id=voucher_id,
            from_date=from_date,
            to_date=to_date,
            skip=skip,
            limit=limit
        )

        results = []
        for e in entries:
            results.append({
                "id": e.id,
                "company_id": e.company_id,
                "fy_id": e.fy_id,
                "voucher_id": e.voucher_id,
                "voucher_number": e.voucher.voucher_number if e.voucher else None,
                "voucher_type": e.voucher.voucher_type.value if e.voucher and hasattr(e.voucher.voucher_type, "value") else (str(e.voucher.voucher_type) if e.voucher else None),
                "posting_date": e.posting_date.isoformat(),
                "ledger_id": e.ledger_id,
                "ledger_name": e.ledger.name if e.ledger else None,
                "debit_amount": float(e.debit_amount),
                "credit_amount": float(e.credit_amount),
                "running_balance": float(e.running_balance),
                "is_reversed": e.is_reversed,
                "created_at": e.created_at.isoformat()
            })

        return jsonify({
            "items": results,
            "total": total,
            "page": page,
            "limit": limit
        }), 200
    except Exception as e:
        logger.error(f"Error fetching General Ledger entries: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_ledger_balances():
    """Returns ledger running totals (Dr, Cr, Net) for the active company."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        repo = VoucherRepository(db)
        balances = repo.get_ledger_balances(company_id=company_id, fy_id=fy_id)
        return jsonify(balances), 200
    except Exception as e:
        logger.error(f"Error fetching ledger balances: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()
