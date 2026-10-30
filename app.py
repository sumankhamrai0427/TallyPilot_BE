"""TallyPilot backend entry point.

app.py explicitly defines all API route endpoints using Flask @app.route
and delegates execution directly to their respective controller functions
(matching EduJunction architecture).
"""
import time
from flask import Flask, jsonify, request, g
from flask_cors import CORS

from utils.config import config
from utils.logger import logger
from database.dbConnection import register_db_teardown, init_db

# Controllers (Pure business logic & handling)
from controller import (
    dashboard_controller,
    files_controller,
    transactions_controller,
    tally_controller,
    logs_controller,
    settings_controller,
)


def create_app() -> Flask:
    """Application factory: initializes Flask, CORS, teardown hooks, and registers all endpoints."""
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # ------------------------------------------------------------
    # CORS Configuration
    # ------------------------------------------------------------
    CORS(
        app,
        origins=config.CORS_ORIGINS if config.CORS_ORIGINS else "*",
        supports_credentials=True
    )

    # ------------------------------------------------------------
    # Database Teardown Hook (Scoped session cleanup per request)
    # ------------------------------------------------------------
    register_db_teardown(app)

    # ------------------------------------------------------------
    # Request Logging & Metrics Hook
    # ------------------------------------------------------------
    @app.before_request
    def _before_request():
        g._start_time = time.time()

    @app.after_request
    def _after_request(response):
        duration_ms = (time.time() - getattr(g, "_start_time", time.time())) * 1000
        status_tag = f"[{response.status_code} OK]" if response.status_code < 400 else f"[{response.status_code} ERR]"
        print(f">> [HTTP {request.method}] {request.path} -> {status_tag} ({duration_ms:.1f}ms)", flush=True)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # ------------------------------------------------------------
    # Error Handlers
    # ------------------------------------------------------------
    @app.errorhandler(500)
    def handle_500(err):
        import traceback
        logger.error(f"Internal Server Error: {err}\n{traceback.format_exc()}")
        return jsonify({"detail": "Internal Server Error", "error": str(err)}), 500

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify({"detail": "Endpoint not found"}), 404

    # ============================================================
    # 1. Root Status Endpoint
    # ============================================================
    @app.route("/", methods=["GET"])
    def root():
        """Root API status endpoint."""
        return jsonify({
            "status": "UP",
            "message": f"{config.APP_NAME} API is running",
            "environment": config.APP_ENV
        })

    # ============================================================
    # 2. Dashboard Endpoints
    # ============================================================
    @app.route("/api/dashboard/summary", methods=["GET"])
    def api_dashboard_summary():
        """Returns real-time KPI metrics, transaction counts, and connection states."""
        return dashboard_controller.get_dashboard_summary()

    # ============================================================
    # 3. File Ingestion Endpoints (Excel & CSV)
    # ============================================================
    @app.route("/api/files/upload", methods=["POST"])
    def api_files_upload():
        """Uploads and ingests a bank statement (.xlsx, .xls, .csv)."""
        return files_controller.upload_bank_statement()

    @app.route("/api/files/scan", methods=["POST"])
    def api_files_scan():
        """Scans the configured input directory for new statement files."""
        return files_controller.scan_input_folder()

    @app.route("/api/files/batches", methods=["GET"])
    def api_files_list_batches():
        """Lists recent imported batches."""
        return files_controller.list_batches()

    @app.route("/api/files/batches/<int:batch_id>", methods=["GET"])
    def api_files_get_batch(batch_id: int):
        """Retrieves an import batch by database ID."""
        return files_controller.get_batch(batch_id)

    # ============================================================
    # 4. Transaction Workflow Endpoints
    # ============================================================
    @app.route("/api/transactions", methods=["GET"])
    def api_transactions_list():
        """Lists transactions with status filtering, search, and pagination."""
        return transactions_controller.list_transactions()

    @app.route("/api/transactions/<int:tx_id>", methods=["GET"])
    def api_transactions_get(tx_id: int):
        """Retrieves a single bank transaction by ID."""
        return transactions_controller.get_transaction(tx_id)

    @app.route("/api/transactions/<int:tx_id>/clarify", methods=["POST"])
    def api_transactions_clarify(tx_id: int):
        """Provides user clarification for ambiguous transactions."""
        return transactions_controller.clarify_transaction(tx_id)

    @app.route("/api/transactions/<int:tx_id>/approve", methods=["POST"])
    def api_transactions_approve(tx_id: int):
        """Approves a transaction and posts it directly to Tally Prime."""
        return transactions_controller.approve_transaction(tx_id)

    @app.route("/api/transactions/batch-approve", methods=["POST"])
    def api_transactions_batch_approve():
        """Batch-approves multiple ready transactions."""
        return transactions_controller.batch_approve_transactions()

    @app.route("/api/transactions/<int:tx_id>/skip", methods=["POST"])
    def api_transactions_skip(tx_id: int):
        """Marks a non-accounting transaction as skipped."""
        return transactions_controller.skip_transaction(tx_id)

    @app.route("/api/transactions/<int:tx_id>/retry", methods=["POST"])
    def api_transactions_retry(tx_id: int):
        """Resets a failed or skipped transaction for retry."""
        return transactions_controller.retry_transaction(tx_id)

    # ============================================================
    # 5. Tally Prime Integration Endpoints
    # ============================================================
    @app.route("/api/tally/health", methods=["GET"])
    def api_tally_health():
        """Checks Tally Prime connection health."""
        return tally_controller.tally_health()

    @app.route("/api/tally/test-connection", methods=["POST"])
    def api_tally_test_connection():
        """Tests connectivity to Tally Prime XML HTTP endpoint."""
        return tally_controller.test_connection()

    @app.route("/api/tally/sync-ledgers", methods=["POST"])
    def api_tally_sync_ledgers():
        """Synchronizes and caches ledgers from Tally Prime."""
        return tally_controller.sync_ledgers()

    @app.route("/api/tally/ledgers", methods=["GET"])
    def api_tally_cached_ledgers():
        """Retrieves locally cached Tally ledgers."""
        return tally_controller.get_cached_ledgers()

    @app.route("/api/tally/submissions", methods=["GET"])
    def api_tally_submissions():
        """Lists durable voucher submission tracking logs."""
        return tally_controller.list_submissions()

    # ============================================================
    # 6. Audit Log Endpoints
    # ============================================================
    @app.route("/api/logs", methods=["GET"])
    def api_logs_list():
        """Lists chronological audit log records."""
        return logs_controller.get_audit_logs()

    @app.route("/api/logs/export-csv", methods=["GET"])
    def api_logs_export_csv():
        """Exports audit log entries as a CSV download."""
        return logs_controller.export_audit_logs_csv()

    # ============================================================
    # 7. Application Settings Endpoints
    # ============================================================
    @app.route("/api/settings", methods=["GET"])
    def api_settings_get():
        """Retrieves system configuration and engine diagnostics."""
        return settings_controller.get_settings()

    @app.route("/api/settings", methods=["PUT"])
    def api_settings_update():
        """Updates runtime application settings."""
        return settings_controller.update_settings()

    # Initialize database tables on app startup
    try:
        init_db()
    except Exception as e:
        logger.warning(f"Database initialization notice: {e}")

    return app


# Create application instance
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=(config.APP_ENV == "development"))