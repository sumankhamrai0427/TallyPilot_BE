"""Tally integration controller handling live/mock connectivity, ledger synchronization,
and voucher submission audit logs.
Follows the EduJunction Flask controller pattern.
"""
from flask import request, jsonify
from database.dbConnection import SessionLocal
from helper.tally_client import TallyClientService
from database.repositories import LedgerRepository, AuditRepository
from model.models import TallySubmission
from model.schemas import TallyLedgerOut


def tally_health():
    """Checks Tally Prime connection health."""
    client = TallyClientService()
    return jsonify(client.test_connection())


def test_connection():
    """Tests connectivity to the configured Tally Prime HTTP XML endpoint."""
    client = TallyClientService()
    return jsonify(client.test_connection())


def sync_ledgers():
    """Syncs ledgers from Tally Prime into the local cache repository."""
    client = TallyClientService()
    db = SessionLocal()
    try:
        ledger_repo = LedgerRepository(db)
        audit_repo = AuditRepository(db)

        ledgers, is_mock = client.sync_ledgers_from_tally()
        if not ledgers:
            return jsonify({"detail": "Failed to retrieve ledgers from Tally Prime. Check Tally XML HTTP server."}), 502

        for item in ledgers:
            ledger_repo.upsert(name=item["name"], parent_group=item["parent_group"])

        all_ledgers = ledger_repo.list_all()

        audit_repo.log(
            action="TALLY_LEDGERS_SYNCED",
            summary=f"Synced {len(ledgers)} ledgers from Tally Prime ({'Mock' if is_mock else 'Live'}).",
            details={"count": len(ledgers), "is_mock": is_mock}
        )

        return jsonify([TallyLedgerOut.model_validate(l).model_dump() for l in all_ledgers])
    finally:
        db.close()


def get_cached_ledgers():
    """Retrieves all locally cached Tally ledgers."""
    db = SessionLocal()
    try:
        ledger_repo = LedgerRepository(db)
        ledgers = ledger_repo.list_all()
        return jsonify([TallyLedgerOut.model_validate(l).model_dump() for l in ledgers])
    finally:
        db.close()


def list_submissions():
    """Lists durable voucher submission tracking logs."""
    limit = request.args.get("limit", default=50, type=int)
    db = SessionLocal()
    try:
        subs = db.query(TallySubmission).order_by(TallySubmission.submitted_at.desc()).limit(limit).all()
        return jsonify([
            {
                "id": s.id,
                "transaction_id": s.transaction_id,
                "company_name": s.company_name,
                "voucher_type": s.voucher_type,
                "voucher_date": s.voucher_date,
                "status": s.status,
                "http_status_code": s.http_status_code,
                "tally_voucher_guid": s.tally_voucher_guid,
                "error_message": s.error_message,
                "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None
            }
            for s in subs
        ])
    finally:
        db.close()
