"""Dashboard controller handling summary KPIs, charts, and connection states.
Follows the EduJunction Flask controller pattern.
"""
from decimal import Decimal
from flask import jsonify
from sqlalchemy import func
from database.dbConnection import SessionLocal
from database.repositories import TransactionRepository, BatchRepository
from helper.local_llm import LocalLLMService
from helper.tally_client import TallyClientService
from model.schemas import DashboardSummaryOut, ImportBatchOut
from model.models import (
    LedgerAccount, AccountGroup, GeneralLedger, Voucher, Document, BankTransaction, ImportBatch
)
from utils.logger import logger


def get_dashboard_summary():
    """Returns real-time KPI metrics, HLA 9.5 financial numbers, transaction counts, and connection states."""
    db = SessionLocal()
    try:
        from helper.tenant import resolve_tenant_context
        company_id, fy_id = resolve_tenant_context(db)

        tx_repo = TransactionRepository(db)
        batch_repo = BatchRepository(db)
        llm_service = LocalLLMService()
        tally_client = TallyClientService()

        status_counts = tx_repo.count_by_status(company_id=company_id)
        total_tx = tx_repo.total_count(company_id=company_id)

        llm_health = llm_service.check_health()
        tally_health = tally_client.test_connection()

        recent_batches = batch_repo.list_recent(company_id=company_id, limit=5)

        # ------------------------------------------------------------------
        # 1. HLA 9.5 Financial Metrics Calculation (Deterministic Double-Entry)
        # ------------------------------------------------------------------
        ledgers = (
            db.query(
                LedgerAccount.id,
                LedgerAccount.name,
                LedgerAccount.opening_balance,
                LedgerAccount.current_balance,
                AccountGroup.name.label("group_name"),
                AccountGroup.code.label("group_code"),
                AccountGroup.group_type
            )
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(LedgerAccount.company_id == company_id)
            .all()
        )

        total_income = Decimal("0.00")
        total_expenditure = Decimal("0.00")
        cash_balance = Decimal("0.00")
        bank_balance = Decimal("0.00")
        outstanding_receivables = Decimal("0.00")
        outstanding_payables = Decimal("0.00")

        for l in ledgers:
            gl_q = db.query(
                func.sum(GeneralLedger.debit_amount).label("dr"),
                func.sum(GeneralLedger.credit_amount).label("cr")
            ).filter(
                GeneralLedger.company_id == company_id,
                GeneralLedger.ledger_id == l.id
            )
            if fy_id:
                gl_q = gl_q.filter(GeneralLedger.fy_id == fy_id)
            gl_res = gl_q.first()

            dr = Decimal(str(gl_res.dr or 0)) if gl_res and gl_res.dr else Decimal("0.00")
            cr = Decimal(str(gl_res.cr or 0)) if gl_res and gl_res.cr else Decimal("0.00")
            op = Decimal(str(l.opening_balance or 0))

            # Income: Net Credit (cr - dr)
            if l.group_type == "INCOME":
                net = cr - dr
                if net == Decimal("0.00") and l.current_balance:
                    net = abs(Decimal(str(l.current_balance)))
                total_income += max(Decimal("0.00"), net)

            # Expenditure: Net Debit (dr - cr)
            elif l.group_type == "EXPENSE":
                net = dr - cr
                if net == Decimal("0.00") and l.current_balance:
                    net = abs(Decimal(str(l.current_balance)))
                else:
                    net = abs(net)
                total_expenditure += net

            # Cash Balance: Group 'Cash-in-hand' (GRP-CSH)
            if l.group_code == "GRP-CSH" or l.group_name == "Cash-in-hand":
                net = op + dr - cr
                if net == Decimal("0.00") and l.current_balance:
                    net = Decimal(str(l.current_balance))
                cash_balance += net

            # Bank Balance: Group 'Bank Accounts' (GRP-BNK)
            elif l.group_code == "GRP-BNK" or l.group_name in ("Bank Accounts", "Bank OD A/c"):
                net = op + dr - cr
                if net == Decimal("0.00") and l.current_balance:
                    net = Decimal(str(l.current_balance))
                bank_balance += net

            # Outstanding Receivables: Sundry Debtors (GRP-SDR)
            elif l.group_code == "GRP-SDR" or l.group_name == "Sundry Debtors":
                net = op + dr - cr
                if net == Decimal("0.00") and l.current_balance:
                    net = Decimal(str(l.current_balance))
                outstanding_receivables += max(Decimal("0.00"), net)

            # Outstanding Payables: Sundry Creditors (GRP-SCR)
            elif l.group_code == "GRP-SCR" or l.group_name == "Sundry Creditors":
                net = op + cr - dr
                if net == Decimal("0.00") and l.current_balance:
                    net = Decimal(str(l.current_balance))
                outstanding_payables += max(Decimal("0.00"), net)

        current_profit_loss = total_income - total_expenditure

        # ------------------------------------------------------------------
        # 2. HLA 9.5 Operational & Document Metrics
        # ------------------------------------------------------------------
        vouchers_pending_count = db.query(Voucher).filter(
            Voucher.company_id == company_id,
            Voucher.status.in_(("DRAFT", "UNDER_REVIEW"))
        ).count()
        tx_pending_approval_count = status_counts.get("PENDING_APPROVAL", 0)
        pending_vouchers = vouchers_pending_count + tx_pending_approval_count

        doc_unprocessed_count = db.query(Document).filter(
            Document.company_id == company_id,
            Document.status.in_(("PENDING", "RECEIVED"))
        ).count()
        tx_unprocessed_count = status_counts.get("RECEIVED", 0) + status_counts.get("PARSED", 0)
        unprocessed_documents = doc_unprocessed_count + tx_unprocessed_count

        doc_failed_count = db.query(Document).filter(
            Document.company_id == company_id,
            Document.status == "FAILED"
        ).count()
        tx_attention_count = status_counts.get("NEEDS_CLARIFICATION", 0) + status_counts.get("FAILED", 0)
        documents_requiring_attention = doc_failed_count + tx_attention_count

        summary_data = DashboardSummaryOut(
            total_income=total_income,
            total_expenditure=total_expenditure,
            current_profit_loss=current_profit_loss,
            cash_balance=cash_balance,
            bank_balance=bank_balance,
            outstanding_receivables=outstanding_receivables,
            outstanding_payables=outstanding_payables,
            pending_vouchers=pending_vouchers,
            unprocessed_documents=unprocessed_documents,
            documents_requiring_attention=documents_requiring_attention,
            total_transactions=total_tx,
            processed_transactions=status_counts.get("PROCESSED", 0),
            clarification_queue_count=status_counts.get("NEEDS_CLARIFICATION", 0),
            approval_queue_count=status_counts.get("PENDING_APPROVAL", 0),
            failed_transactions=status_counts.get("FAILED", 0),
            skipped_transactions=status_counts.get("SKIPPED", 0),
            total_receivables=outstanding_receivables,
            total_payables=outstanding_payables,
            tally_connection_status="connected" if tally_health.get("success") else "offline",
            llm_connection_status="connected" if llm_health.get("available") else "fallback_active",
            recent_batches=[ImportBatchOut.model_validate(b) for b in recent_batches],
            status_distribution=status_counts
        )

        return jsonify(summary_data.model_dump(mode="json"))
    except Exception as e:
        logger.error(f"Error generating dashboard summary: {e}")
        return jsonify({
            "total_income": 0.0,
            "total_expenditure": 0.0,
            "current_profit_loss": 0.0,
            "cash_balance": 0.0,
            "bank_balance": 0.0,
            "outstanding_receivables": 0.0,
            "outstanding_payables": 0.0,
            "pending_vouchers": 0,
            "unprocessed_documents": 0,
            "documents_requiring_attention": 0,
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
