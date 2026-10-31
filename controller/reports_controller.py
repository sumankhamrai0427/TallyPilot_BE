"""Financial Reporting Controller (HLA Part 10).
Deterministic SQL-driven reports for Day Book, Trial Balance, Profit & Loss, and Balance Sheet.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from flask import jsonify, request, Response
import io
import csv

from database.dbConnection import SessionLocal
from helper.tenant import resolve_tenant_context
from model.models import (
    GeneralLedger, Voucher, VoucherLine, LedgerAccount, 
    AccountGroup, FinancialYear, Company
)
from sqlalchemy import func, and_, or_
from utils.logger import logger


def get_day_book():
    """Returns Day Book entries with date and voucher filtering (HLA Part 10.1)."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)

        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")
        voucher_type = request.args.get("voucher_type")
        ledger_id = request.args.get("ledger_id", type=int)

        query = (
            db.query(
                Voucher.voucher_date,
                Voucher.voucher_number,
                Voucher.voucher_type,
                Voucher.narration,
                VoucherLine.line_number,
                LedgerAccount.id.label("ledger_id"),
                LedgerAccount.name.label("ledger_name"),
                VoucherLine.debit_amount,
                VoucherLine.credit_amount,
                Voucher.status
            )
            .join(VoucherLine, VoucherLine.voucher_id == Voucher.id)
            .join(LedgerAccount, LedgerAccount.id == VoucherLine.ledger_id)
            .filter(Voucher.company_id == company_id)
        )

        if fy_id:
            query = query.filter(Voucher.fy_id == fy_id)
        if from_date:
            query = query.filter(Voucher.voucher_date >= from_date)
        if to_date:
            query = query.filter(Voucher.voucher_date <= to_date)
        if voucher_type:
            query = query.filter(Voucher.voucher_type == voucher_type)
        if ledger_id:
            query = query.filter(VoucherLine.ledger_id == ledger_id)

        rows = query.order_by(Voucher.voucher_date.desc(), Voucher.id.desc(), VoucherLine.line_number.asc()).all()

        results = []
        for r in rows:
            results.append({
                "date": r.voucher_date.isoformat(),
                "voucher_number": r.voucher_number,
                "voucher_type": r.voucher_type,
                "narration": r.narration,
                "line_number": r.line_number,
                "ledger_id": r.ledger_id,
                "ledger_name": r.ledger_name,
                "debit_amount": float(r.debit_amount),
                "credit_amount": float(r.credit_amount),
                "status": r.status
            })

        return jsonify({
            "items": results,
            "total_count": len(results),
            "total_debit": sum(r["debit_amount"] for r in results),
            "total_credit": sum(r["credit_amount"] for r in results)
        }), 200
    except Exception as e:
        logger.error(f"Error fetching Day Book: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_trial_balance():
    """Generates the Trial Balance ensuring Total Debit == Total Credit (HLA Part 10.3)."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        as_of_date = request.args.get("as_of_date")

        # Fetch all active ledgers with their group details
        ledgers = (
            db.query(
                LedgerAccount.id,
                LedgerAccount.name,
                LedgerAccount.code,
                LedgerAccount.opening_balance,
                AccountGroup.name.label("group_name"),
                AccountGroup.group_type,
                AccountGroup.nature
            )
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(LedgerAccount.company_id == company_id, LedgerAccount.is_active == True)
            .order_by(AccountGroup.group_type.asc(), LedgerAccount.name.asc())
            .all()
        )

        tb_items = []
        grand_opening_dr = Decimal("0.00")
        grand_opening_cr = Decimal("0.00")
        grand_period_dr = Decimal("0.00")
        grand_period_cr = Decimal("0.00")
        grand_closing_dr = Decimal("0.00")
        grand_closing_cr = Decimal("0.00")

        for l in ledgers:
            # Query posted general ledger lines
            gl_query = db.query(
                func.sum(GeneralLedger.debit_amount).label("period_dr"),
                func.sum(GeneralLedger.credit_amount).label("period_cr")
            ).filter(
                GeneralLedger.company_id == company_id,
                GeneralLedger.ledger_id == l.id
            )

            if fy_id:
                gl_query = gl_query.filter(GeneralLedger.fy_id == fy_id)
            if as_of_date:
                gl_query = gl_query.filter(GeneralLedger.posting_date <= as_of_date)

            gl_res = gl_query.first()
            p_dr = Decimal(str(gl_res.period_dr or 0)) if gl_res else Decimal("0.00")
            p_cr = Decimal(str(gl_res.period_cr or 0)) if gl_res else Decimal("0.00")

            # Opening balance based on nature
            op_bal = Decimal(str(l.opening_balance or 0))
            op_dr = op_bal if l.nature == "DEBIT" and op_bal >= 0 else Decimal("0.00")
            op_cr = op_bal if l.nature == "CREDIT" and op_bal >= 0 else Decimal("0.00")

            # Net closing calculation
            net_closing = (op_dr + p_dr) - (op_cr + p_cr)
            cl_dr = net_closing if net_closing >= 0 else Decimal("0.00")
            cl_cr = abs(net_closing) if net_closing < 0 else Decimal("0.00")

            grand_opening_dr += op_dr
            grand_opening_cr += op_cr
            grand_period_dr += p_dr
            grand_period_cr += p_cr
            grand_closing_dr += cl_dr
            grand_closing_cr += cl_cr

            tb_items.append({
                "ledger_id": l.id,
                "ledger_name": l.name,
                "ledger_code": l.code,
                "group_name": l.group_name,
                "group_type": l.group_type,
                "opening_debit": float(op_dr),
                "opening_credit": float(op_cr),
                "period_debit": float(p_dr),
                "period_credit": float(p_cr),
                "closing_debit": float(cl_dr),
                "closing_credit": float(cl_cr),
            })

        is_balanced = grand_closing_dr == grand_closing_cr
        discrepancy = float(abs(grand_closing_dr - grand_closing_cr))

        return jsonify({
            "items": tb_items,
            "grand_opening_debit": float(grand_opening_dr),
            "grand_opening_credit": float(grand_opening_cr),
            "grand_period_debit": float(grand_period_dr),
            "grand_period_credit": float(grand_period_cr),
            "grand_closing_debit": float(grand_closing_dr),
            "grand_closing_credit": float(grand_closing_cr),
            "is_balanced": is_balanced,
            "discrepancy": discrepancy
        }), 200
    except Exception as e:
        logger.error(f"Error generating Trial Balance: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_profit_and_loss():
    """Generates Profit and Loss statement (HLA Part 10.4)."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        # Income and Expense accounts
        accounts = (
            db.query(
                LedgerAccount.id,
                LedgerAccount.name,
                AccountGroup.group_type,
                AccountGroup.name.label("group_name")
            )
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.group_type.in_(("INCOME", "EXPENSE"))
            )
            .all()
        )

        income_items = []
        expense_items = []
        total_income = Decimal("0.00")
        total_expense = Decimal("0.00")

        for acc in accounts:
            q = db.query(
                func.sum(GeneralLedger.debit_amount).label("dr"),
                func.sum(GeneralLedger.credit_amount).label("cr")
            ).filter(
                GeneralLedger.company_id == company_id,
                GeneralLedger.ledger_id == acc.id
            )
            if fy_id:
                q = q.filter(GeneralLedger.fy_id == fy_id)
            if from_date:
                q = q.filter(GeneralLedger.posting_date >= from_date)
            if to_date:
                q = q.filter(GeneralLedger.posting_date <= to_date)

            res = q.first()
            dr = Decimal(str(res.dr or 0)) if res else Decimal("0.00")
            cr = Decimal(str(res.cr or 0)) if res else Decimal("0.00")

            if acc.group_type == "INCOME":
                net = cr - dr
                total_income += net
                income_items.append({
                    "ledger_id": acc.id,
                    "ledger_name": acc.name,
                    "group_name": acc.group_name,
                    "amount": float(net)
                })
            else:
                net = dr - cr
                total_expense += net
                expense_items.append({
                    "ledger_id": acc.id,
                    "ledger_name": acc.name,
                    "group_name": acc.group_name,
                    "amount": float(net)
                })

        net_profit_loss = total_income - total_expense

        return jsonify({
            "income": {
                "items": income_items,
                "total": float(total_income)
            },
            "expenses": {
                "items": expense_items,
                "total": float(total_expense)
            },
            "net_profit_loss": float(net_profit_loss),
            "status": "PROFIT" if net_profit_loss >= 0 else "LOSS"
        }), 200
    except Exception as e:
        logger.error(f"Error generating Profit & Loss: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_balance_sheet():
    """Generates the Balance Sheet: Assets = Liabilities + Equity (HLA Part 10.5)."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        as_of_date = request.args.get("as_of_date")

        accounts = (
            db.query(
                LedgerAccount.id,
                LedgerAccount.name,
                LedgerAccount.opening_balance,
                AccountGroup.group_type,
                AccountGroup.name.label("group_name"),
                AccountGroup.nature
            )
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.group_type.in_(("ASSET", "LIABILITY", "EQUITY"))
            )
            .all()
        )

        assets = []
        liabilities = []
        equity = []
        total_assets = Decimal("0.00")
        total_liabilities = Decimal("0.00")
        total_equity = Decimal("0.00")

        for acc in accounts:
            q = db.query(
                func.sum(GeneralLedger.debit_amount).label("dr"),
                func.sum(GeneralLedger.credit_amount).label("cr")
            ).filter(
                GeneralLedger.company_id == company_id,
                GeneralLedger.ledger_id == acc.id
            )
            if fy_id:
                q = q.filter(GeneralLedger.fy_id == fy_id)
            if as_of_date:
                q = q.filter(GeneralLedger.posting_date <= as_of_date)

            res = q.first()
            dr = Decimal(str(res.dr or 0)) if res else Decimal("0.00")
            cr = Decimal(str(res.cr or 0)) if res else Decimal("0.00")
            op = Decimal(str(acc.opening_balance or 0))

            if acc.group_type == "ASSET":
                net = (op if acc.nature == "DEBIT" else Decimal("0.00")) + dr - cr
                total_assets += net
                assets.append({
                    "ledger_id": acc.id,
                    "ledger_name": acc.name,
                    "group_name": acc.group_name,
                    "amount": float(net)
                })
            elif acc.group_type == "LIABILITY":
                net = (op if acc.nature == "CREDIT" else Decimal("0.00")) + cr - dr
                total_liabilities += net
                liabilities.append({
                    "ledger_id": acc.id,
                    "ledger_name": acc.name,
                    "group_name": acc.group_name,
                    "amount": float(net)
                })
            else: # EQUITY
                net = (op if acc.nature == "CREDIT" else Decimal("0.00")) + cr - dr
                total_equity += net
                equity.append({
                    "ledger_id": acc.id,
                    "ledger_name": acc.name,
                    "group_name": acc.group_name,
                    "amount": float(net)
                })

        # Calculate current year Net Profit to balance equity
        pl_data = get_profit_and_loss()
        current_year_pl = Decimal(str(pl_data[0].get_json().get("net_profit_loss", 0)))
        total_equity += current_year_pl

        equity.append({
            "ledger_id": 0,
            "ledger_name": "Current Period Profit / Loss",
            "group_name": "Reserves and Surplus",
            "amount": float(current_year_pl)
        })

        total_liab_and_equity = total_liabilities + total_equity
        is_balanced = abs(total_assets - total_liab_and_equity) < Decimal("0.01")

        return jsonify({
            "assets": {
                "items": assets,
                "total": float(total_assets)
            },
            "liabilities": {
                "items": liabilities,
                "total": float(total_liabilities)
            },
            "equity": {
                "items": equity,
                "total": float(total_equity)
            },
            "total_assets": float(total_assets),
            "total_liabilities_and_equity": float(total_liab_and_equity),
            "is_balanced": is_balanced,
            "discrepancy": float(abs(total_assets - total_liab_and_equity))
        }), 200
    except Exception as e:
        logger.error(f"Error generating Balance Sheet: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()

