"""Dashboard controller handling summary KPIs, charts, and connection states.
Follows the EduJunction Flask controller pattern.
"""
from flask import jsonify
from database.dbConnection import SessionLocal
from database.repositories import TransactionRepository, BatchRepository
from helper.local_llm import LocalLLMService
from helper.tally_client import TallyClientService
from model.schemas import DashboardSummaryOut, ImportBatchOut


def get_dashboard_summary():
    """Returns real-time KPI metrics, transaction counts, and connection states."""
    db = SessionLocal()
    try:
        from helper.tenant import resolve_tenant_context
        company_id, _ = resolve_tenant_context(db)

        tx_repo = TransactionRepository(db)
        batch_repo = BatchRepository(db)
        llm_service = LocalLLMService()
        tally_client = TallyClientService()

        status_counts = tx_repo.count_by_status(company_id=company_id)
        total_tx = tx_repo.total_count(company_id=company_id)

        llm_health = llm_service.check_health()
        tally_health = tally_client.test_connection()

        recent_batches = batch_repo.list_recent(company_id=company_id, limit=5)

        summary_data = DashboardSummaryOut(
            total_transactions=total_tx,
            processed_transactions=status_counts.get("PROCESSED", 0),
            clarification_queue_count=status_counts.get("NEEDS_CLARIFICATION", 0),
            approval_queue_count=status_counts.get("PENDING_APPROVAL", 0),
            failed_transactions=status_counts.get("FAILED", 0),
            skipped_transactions=status_counts.get("SKIPPED", 0),
            tally_connection_status="connected" if tally_health.get("success") else "offline",
            llm_connection_status="connected" if llm_health.get("available") else "fallback_active",
            recent_batches=[ImportBatchOut.model_validate(b) for b in recent_batches],
            status_distribution=status_counts
        )

        return jsonify(summary_data.model_dump(mode="json"))
    except Exception as e:
        from utils.logger import logger
        logger.error(f"Error generating dashboard summary: {e}")
        return jsonify({
            "total_transactions": 0,
            "processed_transactions": 0,
            "clarification_queue_count": 0,
            "approval_queue_count": 0,
            "failed_transactions": 0,
            "skipped_transactions": 0,
            "tally_connection_status": "offline",
            "llm_connection_status": "fallback_active",
            "recent_batches": [],
            "status_distribution": {}
        }), 200
    finally:
        db.close()
