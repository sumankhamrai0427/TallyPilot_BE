"""AI Accounting Assistant & Tool Registry Controller (HLA Part 9 & Part 12).
Interprets natural-language user instructions, executes deterministic accounting tools,
and records conversation history in chat_sessions / chat_messages.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, List
from flask import jsonify, request
import json

from database.dbConnection import SessionLocal
from helper.tenant import resolve_tenant_context
from helper.local_llm import LocalLLMService
from model.models import (
    ChatSession, ChatMessage, LedgerAccount, AccountGroup, 
    Voucher, VoucherLine, BankTransaction, GeneralLedger
)
from services.voucher_service import VoucherService
from controller.reports_controller import get_trial_balance, get_profit_and_loss, get_day_book, get_balance_sheet
from utils.logger import logger


class AccountingToolRegistry:
    """Deterministic tool execution registry for the Local LLM (HLA Part 12.3)."""

    @staticmethod
    def execute_tool(tool_name: str, args: Dict[str, Any], db, company_id: int, fy_id: int) -> Dict[str, Any]:
        if tool_name == "search_ledgers":
            query = args.get("query", "")
            ledgers = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name.ilike(f"%{query}%")
            ).limit(10).all()
            return {
                "results": [{"id": l.id, "name": l.name, "current_balance": float(l.current_balance)} for l in ledgers]
            }

        elif tool_name == "get_ledger_balance":
            ledger_name = args.get("ledger_name", "")
            ledger = db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name.ilike(f"%{ledger_name}%")
            ).first()
            if not ledger:
                return {"error": f"Ledger '{ledger_name}' not found."}
            return {
                "ledger_id": ledger.id,
                "ledger_name": ledger.name,
                "current_balance": float(ledger.current_balance),
                "opening_balance": float(ledger.opening_balance)
            }

        elif tool_name == "get_trial_balance_summary":
            res, _ = get_trial_balance()
            data = res.get_json()
            return {
                "is_balanced": data.get("is_balanced"),
                "total_debit": data.get("grand_closing_debit"),
                "total_credit": data.get("grand_closing_credit"),
                "item_count": len(data.get("items", []))
            }

        elif tool_name == "get_profit_loss_summary":
            res, _ = get_profit_and_loss()
            data = res.get_json()
            return {
                "total_income": data.get("income", {}).get("total"),
                "total_expenses": data.get("expenses", {}).get("total"),
                "net_profit_loss": data.get("net_profit_loss"),
                "status": data.get("status")
            }

        elif tool_name == "create_voucher_draft":
            voucher_type = args.get("voucher_type", "Payment")
            amount = Decimal(str(args.get("amount", 0)))
            narration = args.get("narration", "Created by AI Assistant")
            dr_ledger_name = args.get("debit_ledger")
            cr_ledger_name = args.get("credit_ledger")

            dr_acc = db.query(LedgerAccount).filter(LedgerAccount.company_id == company_id, LedgerAccount.name.ilike(f"%{dr_ledger_name}%")).first()
            cr_acc = db.query(LedgerAccount).filter(LedgerAccount.company_id == company_id, LedgerAccount.name.ilike(f"%{cr_ledger_name}%")).first()

            if not dr_acc or not cr_acc:
                return {"error": f"Could not match ledgers '{dr_ledger_name}' or '{cr_ledger_name}'."}

            lines = [
                {"ledger_id": dr_acc.id, "debit_amount": amount, "credit_amount": Decimal("0.00"), "narration": narration},
                {"ledger_id": cr_acc.id, "debit_amount": Decimal("0.00"), "credit_amount": amount, "narration": narration}
            ]

            voucher = VoucherService.create_voucher(
                db=db,
                company_id=company_id,
                voucher_type=voucher_type,
                voucher_date=date.today(),
                narration=narration,
                lines_data=lines,
                created_by="AI_ASSISTANT",
                auto_post=False
            )
            db.commit()
            return {
                "success": True,
                "voucher_number": voucher.voucher_number,
                "voucher_id": voucher.id,
                "status": "DRAFT",
                "message": f"Draft {voucher_type} voucher {voucher.voucher_number} created for ₹{amount}."
            }

        return {"error": f"Unknown tool: {tool_name}"}


def get_chat_sessions():
    """Lists recent conversation sessions for the active company."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.company_id == company_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(20)
            .all()
        )
        return jsonify([
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat()
            }
            for s in sessions
        ]), 200
    except Exception as e:
        logger.error(f"Error listing chat sessions: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_chat_history(session_id: int):
    """Retrieves messages for a specific chat session."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.company_id == company_id).first()
        if not session:
            return jsonify({"detail": "Session not found"}), 404

        messages = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc()).all()
        return jsonify({
            "session_id": session.id,
            "title": session.title,
            "messages": [
                {
                    "id": m.id,
                    "sender": m.sender,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                    "created_at": m.created_at.isoformat()
                }
                for m in messages
            ]
        }), 200
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def post_chat_message():
    """Processes a user message via Local LLM and executes tools if required (HLA Part 12)."""
    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        payload = request.get_json() or {}
        user_text = payload.get("message", "").strip()
        session_id = payload.get("session_id")

        if not user_text:
            return jsonify({"detail": "Message text is required"}), 400

        # Get or create chat session
        if session_id:
            chat_session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.company_id == company_id).first()
        else:
            chat_session = None

        if not chat_session:
            chat_session = ChatSession(
                company_id=company_id,
                title=user_text[:40] + ("..." if len(user_text) > 40 else ""),
                created_at=datetime.utcnow()
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)

        # Save user message
        user_msg = ChatMessage(
            session_id=chat_session.id,
            sender="USER",
            content=user_text,
            created_at=datetime.utcnow()
        )
        db.add(user_msg)
        db.commit()

        # Query Local LLM with System Prompt & Tool definitions
        llm = LocalLLMService()

        # Tool detection heuristics / Intent classification
        tool_executed = None
        tool_result = None
        lower_text = user_text.lower()

        if "trial balance" in lower_text or "tb" in lower_text:
            tool_executed = "get_trial_balance_summary"
            tool_result = AccountingToolRegistry.execute_tool("get_trial_balance_summary", {}, db, company_id, fy_id)
            assistant_reply = (
                f"**Trial Balance Status:** {'Balanced' if tool_result.get('is_balanced') else 'Discrepancy'}\n"
                f"- Total Debit: ₹{tool_result.get('total_debit', 0):,.2f}\n"
                f"- Total Credit: ₹{tool_result.get('total_credit', 0):,.2f}\n"
                f"- Total Accounts: {tool_result.get('item_count')}\n\n"
                f"You can view the full Trial Balance under the **Financial Reports** section."
            )
        elif "profit" in lower_text or "loss" in lower_text or "p&l" in lower_text:
            tool_executed = "get_profit_loss_summary"
            tool_result = AccountingToolRegistry.execute_tool("get_profit_loss_summary", {}, db, company_id, fy_id)
            net = tool_result.get('net_profit_loss', 0)
            status = tool_result.get('status', 'PROFIT')
            assistant_reply = (
                f"**Current Financial Year Profit & Loss Summary:**\n"
                f"- Total Revenue / Income: ₹{tool_result.get('total_income', 0):,.2f}\n"
                f"- Total Expenses: ₹{tool_result.get('total_expenses', 0):,.2f}\n"
                f"- Net Result: **₹{abs(net):,.2f} ({status})**\n\n"
                f"Check the **Financial Reports** page for a detailed itemized breakdown."
            )
        elif "balance of" in lower_text or "balance for" in lower_text:
            words = user_text.split()
            # extract ledger search keyword
            kw = words[-1] if words else "Bank"
            tool_executed = "get_ledger_balance"
            tool_result = AccountingToolRegistry.execute_tool("get_ledger_balance", {"ledger_name": kw}, db, company_id, fy_id)
            if "error" in tool_result:
                assistant_reply = tool_result["error"]
            else:
                assistant_reply = f"The current balance for **{tool_result['ledger_name']}** is **₹{tool_result['current_balance']:,.2f}**."
        else:
            # General conversation via LLM prompt
            prompt = (
                f"You are the TallyPilot AI Accounting Assistant running 100% locally on Windows. "
                f"You assist accountants with double-entry bookkeeping, ledger inquiries, and vouchers.\n\n"
                f"User Question: {user_text}\n\n"
                f"Respond concisely with professional accounting insights."
            )
            assistant_reply = llm.generate_response(prompt) or "I am your Local AI Accounting Assistant. How can I assist you with your books today?"

        # Save assistant message
        asst_msg = ChatMessage(
            session_id=chat_session.id,
            sender="ASSISTANT",
            content=assistant_reply,
            tool_calls={"tool": tool_executed, "result": tool_result} if tool_executed else None,
            created_at=datetime.utcnow()
        )
        db.add(asst_msg)
        chat_session.updated_at = datetime.utcnow()
        db.commit()

        return jsonify({
            "session_id": chat_session.id,
            "reply": assistant_reply,
            "tool_calls": asst_msg.tool_calls
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error in assistant chat: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()

