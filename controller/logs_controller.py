"""Audit logs controller providing queryable audit trail records and CSV exports.
Follows the EduJunction Flask controller pattern.
"""
import csv
import io
from flask import request, jsonify, Response
from database.dbConnection import SessionLocal
from database.repositories import AuditRepository
from model.schemas import AuditLogOut


def get_audit_logs():
    """Lists chronological audit log records with optional filtering."""
    action = request.args.get("action", default=None, type=str)
    transaction_id = request.args.get("transaction_id", default=None, type=int)
    batch_id = request.args.get("batch_id", default=None, type=int)
    page = request.args.get("page", default=1, type=int)
    page_size = request.args.get("page_size", default=50, type=int)

    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    db = SessionLocal()
    try:
        repo = AuditRepository(db)
        skip = (page - 1) * page_size
        items, total = repo.list_filtered(
            action=action,
            transaction_id=transaction_id,
            batch_id=batch_id,
            skip=skip,
            limit=page_size
        )

        return jsonify({
            "items": [AuditLogOut.model_validate(log).model_dump() for log in items],
            "total": total,
            "page": page,
            "page_size": page_size
        })
    finally:
        db.close()


def export_audit_logs_csv():
    """Exports audit log entries as a downloadable CSV file."""
    action = request.args.get("action", default=None, type=str)

    db = SessionLocal()
    try:
        repo = AuditRepository(db)
        items, _ = repo.list_filtered(action=action, skip=0, limit=2000)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Timestamp", "Actor", "Action", "Batch ID", "Transaction ID", "Previous Status", "New Status", "Summary"])

        for item in items:
            writer.writerow([
                item.id,
                item.timestamp.isoformat() if item.timestamp else "",
                item.actor,
                item.action,
                item.batch_id or "",
                item.transaction_id or "",
                item.previous_status or "",
                item.new_status or "",
                item.summary or ""
            ])

        csv_content = output.getvalue()
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=tallypilot_audit_logs.csv"}
        )
    finally:
        db.close()
