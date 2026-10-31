"""Transactions controller handling listing, pagination, clarifications,
approvals, skips, and retry actions.
Follows the EduJunction Flask controller pattern.
"""
from typing import Optional
from flask import request, jsonify
from database.dbConnection import SessionLocal
from database.repositories import TransactionRepository
from helper.workflow_service import WorkflowService
from model.schemas import (
    BankTransactionOut,
    ClarifyTransactionRequest,
    ApproveTransactionRequest,
    SkipTransactionRequest,
    BatchApproveRequest
)


def list_transactions():
    """Lists bank transactions with optional status, search, and pagination filters."""
    batch_id = request.args.get("batch_id", default=None, type=int)
    status = request.args.get("status", default=None, type=str)
    search = request.args.get("search", default=None, type=str)
    requires_review_param = request.args.get("requires_review", default=None, type=str)
    requires_review = None
    if requires_review_param is not None:
        requires_review = requires_review_param.lower() in ("true", "1", "yes")

    page = request.args.get("page", default=1, type=int)
    page_size = request.args.get("page_size", default=25, type=int)

    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    db = SessionLocal()
    try:
        from helper.tenant import resolve_tenant_context
        company_id, _ = resolve_tenant_context(db)
        repo = TransactionRepository(db)
        skip = (page - 1) * page_size
        items, total = repo.list_filtered(
            company_id=company_id,
            batch_id=batch_id,
            status=status,
            search=search,
            requires_review=requires_review,
            skip=skip,
            limit=page_size
        )

        return jsonify({
            "items": [BankTransactionOut.model_validate(t).model_dump() for t in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 1
        })
    finally:
        db.close()


def get_transaction(tx_id: int):
    """Retrieves a single bank transaction by ID."""
    db = SessionLocal()
    try:
        repo = TransactionRepository(db)
        tx = repo.get_by_id(tx_id)
        if not tx:
            return jsonify({"detail": "Transaction not found"}), 404
        return jsonify(BankTransactionOut.model_validate(tx).model_dump())
    finally:
        db.close()


def clarify_transaction(tx_id: int):
    """Provides human clarification to resolve an ambiguous transaction."""
    payload = request.get_json(silent=True) or {}
    try:
        req = ClarifyTransactionRequest(**payload)
    except Exception as e:
        return jsonify({"detail": f"Invalid clarification payload: {str(e)}"}), 422

    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        updated_tx = workflow.clarify_transaction(tx_id, req)
        return jsonify(BankTransactionOut.model_validate(updated_tx).model_dump())
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": f"Failed to clarify transaction: {str(e)}"}), 500
    finally:
        db.close()


def approve_transaction(tx_id: int):
    """Approves a transaction and posts it directly to Tally Prime."""
    payload = request.get_json(silent=True) or {}
    try:
        req = ApproveTransactionRequest(**payload)
    except Exception as e:
        return jsonify({"detail": f"Invalid approval payload: {str(e)}"}), 422

    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        result = workflow.approve_and_post_transaction(tx_id, req)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": f"Approval submission error: {str(e)}"}), 500
    finally:
        db.close()


def batch_approve_transactions():
    """Approves multiple transactions in batch and posts them to Tally Prime."""
    payload = request.get_json(silent=True) or {}
    try:
        req = BatchApproveRequest(**payload)
    except Exception as e:
        return jsonify({"detail": f"Invalid batch approval payload: {str(e)}"}), 422

    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        results = []
        for tx_id in req.transaction_ids:
            try:
                single_req = ApproveTransactionRequest(
                    approver_user=req.approver_user,
                    approval_notes="Batch approved"
                )
                res = workflow.approve_and_post_transaction(tx_id, single_req)
                results.append(res)
            except Exception as e:
                results.append({"transaction_id": tx_id, "success": False, "error": str(e)})

        return jsonify({
            "total_requested": len(req.transaction_ids),
            "successful": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "details": results
        })
    finally:
        db.close()


def skip_transaction(tx_id: int):
    """Marks a non-accounting transaction as skipped."""
    payload = request.get_json(silent=True) or {}
    try:
        req = SkipTransactionRequest(**payload)
    except Exception as e:
        return jsonify({"detail": f"Invalid skip payload: {str(e)}"}), 422

    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        tx = workflow.skip_transaction(tx_id, req.reason)
        return jsonify(BankTransactionOut.model_validate(tx).model_dump())
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": f"Failed to skip transaction: {str(e)}"}), 500
    finally:
        db.close()


def retry_transaction(tx_id: int):
    """Resets a failed or skipped transaction back to pending approval."""
    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        tx = workflow.retry_transaction(tx_id)
        return jsonify(BankTransactionOut.model_validate(tx).model_dump())
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": f"Failed to retry transaction: {str(e)}"}), 500
    finally:
        db.close()
