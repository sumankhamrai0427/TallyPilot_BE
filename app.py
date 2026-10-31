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
    vouchers_controller,
    ledgers_controller,
    reconciliation_controller,
    reports_controller,
    assistant_controller,
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

    # ============================================================
    # 8. Multi-Tenant Companies & Ledgers Endpoints
    # ============================================================
    @app.route("/api/companies", methods=["GET"])
    def api_companies_list():
        """Lists active companies."""
        return ledgers_controller.list_companies()

    @app.route("/api/companies/<int:company_id>", methods=["GET"])
    def api_company_get(company_id: int):
        """Retrieves a single company profile with credentials."""
        return ledgers_controller.get_company(company_id)

    @app.route("/api/companies", methods=["POST"])
    def api_company_create():
        """Creates a new company master with credentials."""
        return ledgers_controller.create_company()

    @app.route("/api/companies/<int:company_id>", methods=["PUT"])
    def api_company_update(company_id: int):
        """Updates company details and credentials."""
        return ledgers_controller.update_company(company_id)

    @app.route("/api/companies/<int:company_id>/test-tally", methods=["POST"])
    def api_company_test_tally(company_id: int):
        """Tests live Tally Prime connection for a company."""
        return ledgers_controller.test_company_tally(company_id)

    @app.route("/api/financial-years", methods=["GET"])
    def api_financial_years_list():
        """Lists financial years for the active company."""
        return ledgers_controller.list_financial_years()

    @app.route("/api/financial-years", methods=["POST"])
    def api_financial_year_create():
        """Creates a new financial year."""
        return ledgers_controller.create_financial_year()

    @app.route("/api/financial-years/<int:fy_id>/set-current", methods=["PUT"])
    def api_financial_year_set_current(fy_id: int):
        """Sets active financial year."""
        return ledgers_controller.set_current_financial_year(fy_id)

    @app.route("/api/financial-years/<int:fy_id>/toggle-lock", methods=["PUT"])
    def api_financial_year_toggle_lock(fy_id: int):
        """Locks/unlocks financial year (closing control)."""
        return ledgers_controller.toggle_financial_year_lock(fy_id)

    @app.route("/api/chart-of-accounts", methods=["GET"])
    def api_chart_of_accounts():
        """Retrieves hierarchical Chart of Accounts tree."""
        return ledgers_controller.get_chart_of_accounts()

    @app.route("/api/ledgers", methods=["GET"])
    def api_ledgers_list():
        """Retrieves flat list of active ledger accounts."""
        return ledgers_controller.list_ledgers()

    @app.route("/api/parties", methods=["GET"])
    def api_parties_list():
        """Retrieves active parties for the company."""
        return ledgers_controller.list_parties()

    # ============================================================
    # 9. Double-Entry Vouchers & General Ledger Endpoints
    # ============================================================
    @app.route("/api/vouchers", methods=["GET"])
    def api_vouchers_list():
        """Lists double-entry vouchers with filtering and pagination."""
        return vouchers_controller.list_vouchers()

    @app.route("/api/vouchers", methods=["POST"])
    def api_vouchers_create():
        """Creates a double-entry voucher with balanced lines."""
        return vouchers_controller.create_voucher()

    @app.route("/api/vouchers/<int:voucher_id>", methods=["GET"])
    def api_vouchers_get(voucher_id: int):
        """Retrieves full details of a voucher."""
        return vouchers_controller.get_voucher(voucher_id)

    @app.route("/api/vouchers/<int:voucher_id>/post", methods=["POST"])
    def api_vouchers_post(voucher_id: int):
        """Posts an approved voucher to the General Ledger."""
        return vouchers_controller.post_voucher(voucher_id)

    @app.route("/api/vouchers/generate-from-transaction/<int:tx_id>", methods=["POST"])
    def api_vouchers_generate_from_tx(tx_id: int):
        """Auto-generates balanced double-entry voucher from a bank transaction."""
        return vouchers_controller.generate_voucher_from_transaction(tx_id)

    @app.route("/api/gl-entries", methods=["GET"])
    def api_gl_entries_list():
        """Lists General Ledger postings with ledger/date filtering."""
        return vouchers_controller.get_general_ledger_entries()

    @app.route("/api/ledger-balances", methods=["GET"])
    def api_ledger_balances():
        """Returns running ledger balances."""
        return vouchers_controller.get_ledger_balances()

    # ============================================================
    # 10. Bank Reconciliation Endpoints
    # ============================================================
    @app.route("/api/reconciliation/summary", methods=["GET"])
    def api_recon_summary():
        """Returns reconciliation KPIs and bank account balances."""
        return reconciliation_controller.get_reconciliation_summary()

    @app.route("/api/reconciliation/unmatched", methods=["GET"])
    def api_recon_unmatched():
        """Returns unreconciled bank transactions and open voucher lines."""
        return reconciliation_controller.list_unmatched_items()

    @app.route("/api/reconciliation/match", methods=["POST"])
    def api_recon_match():
        """Matches a bank transaction with a voucher line."""
        return reconciliation_controller.match_transaction()

    # ============================================================
    # 11. Financial Reporting Endpoints (HLA Part 10)
    # ============================================================
    @app.route("/api/reports/day-book", methods=["GET"])
    def api_reports_day_book():
        """Returns filtered Day Book entries."""
        return reports_controller.get_day_book()

    @app.route("/api/reports/trial-balance", methods=["GET"])
    def api_reports_trial_balance():
        """Generates deterministic Trial Balance (Debit == Credit)."""
        return reports_controller.get_trial_balance()

    @app.route("/api/reports/profit-loss", methods=["GET"])
    def api_reports_profit_loss():
        """Generates Profit and Loss statement."""
        return reports_controller.get_profit_and_loss()

    @app.route("/api/reports/balance-sheet", methods=["GET"])
    def api_reports_balance_sheet():
        """Generates Balance Sheet (Assets = Liabilities + Equity)."""
        return reports_controller.get_balance_sheet()

    # ============================================================
    # 12. AI Accounting Assistant Endpoints (HLA Part 9 & 12)
    # ============================================================
    @app.route("/api/assistant/sessions", methods=["GET"])
    def api_assistant_sessions():
        """Lists chat conversation sessions."""
        return assistant_controller.get_chat_sessions()

    @app.route("/api/assistant/history/<int:session_id>", methods=["GET"])
    def api_assistant_history(session_id: int):
        """Retrieves chat message history for a session."""
        return assistant_controller.get_chat_history(session_id)

    @app.route("/api/assistant/chat", methods=["POST"])
    def api_assistant_chat():
        """Processes conversational query and executes accounting tools."""
        return assistant_controller.post_chat_message()

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