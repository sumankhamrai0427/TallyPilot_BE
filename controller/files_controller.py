"""File ingestion controller handling bank statement uploads (.xlsx, .xls, .csv),
folder scanning, and batch retrieval.
Follows the EduJunction Flask controller pattern.
"""
import os
import shutil
from flask import request, jsonify
from database.dbConnection import SessionLocal
from utils.config import config
from helper.workflow_service import WorkflowService
from database.repositories import BatchRepository, DocumentRepository
from model.schemas import ImportBatchOut
from helper.tenant import resolve_tenant_context


def upload_bank_statement():
    """Uploads and ingests one or multiple bank statement files (.xlsx, .xls, .csv, .pdf, .txt)."""
    # Collect files from 'files' or 'file' form fields
    uploaded_files = request.files.getlist("files")
    if not uploaded_files or (len(uploaded_files) == 1 and not uploaded_files[0].filename):
        uploaded_files = request.files.getlist("file")

    if not uploaded_files or not any(f.filename for f in uploaded_files):
        return jsonify({"detail": "No files uploaded. Provide file(s) in form field 'files' or 'file'"}), 400

    valid_extensions = [".xlsx", ".xls", ".csv", ".pdf", ".txt"]
    successful_batches = []
    failed_files = []

    db = SessionLocal()
    try:
        company_id, fy_id = resolve_tenant_context(db)
        bank_ledger_id = request.form.get("bank_ledger_id", type=int) or request.args.get("bank_ledger_id", type=int)
        company_input_dir = config.get_company_input_dir(company_id)
        workflow = WorkflowService(db)
        for uploaded_file in uploaded_files:
            if not uploaded_file.filename:
                continue

            filename = uploaded_file.filename
            ext = os.path.splitext(filename)[1].lower()
            if ext not in valid_extensions:
                failed_files.append({
                    "filename": filename,
                    "error": f"Unsupported format '{ext}'. Supported: {', '.join(valid_extensions)}"
                })
                continue

            destination_path = os.path.join(company_input_dir, filename)
            try:
                try:
                    uploaded_file.save(destination_path)
                except PermissionError:
                    # Fallback if original file is locked (e.g. open in Excel)
                    import time
                    name_part, ext_part = os.path.splitext(filename)
                    alt_filename = f"{name_part}_{int(time.time())}{ext_part}"
                    destination_path = os.path.join(company_input_dir, alt_filename)
                    uploaded_file.save(destination_path)
                    filename = alt_filename

                batch = workflow.ingest_excel_file(
                    destination_path,
                    filename,
                    company_id=company_id,
                    fy_id=fy_id,
                    bank_ledger_id=bank_ledger_id
                )
                batch_dict = ImportBatchOut.model_validate(batch).model_dump(mode="json")
                successful_batches.append(batch_dict)
            except ValueError as ve:
                try:
                    db.rollback()
                except Exception:
                    pass
                err_msg = str(ve)
                is_dup = "Duplicate file detected" in err_msg
                failed_files.append({
                    "filename": filename,
                    "error": err_msg,
                    "is_duplicate": is_dup
                })
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                failed_files.append({"filename": filename, "error": f"Processing error: {str(e)}", "is_duplicate": False})

        # Backward compatibility for single file upload
        if len(uploaded_files) == 1 and len(successful_batches) == 1 and not failed_files:
            batch_copy = dict(successful_batches[0])
            res_payload = {
                **batch_copy,
                "success": True,
                "batches": [dict(batch_copy)],
                "total_files": 1,
                "successful_count": 1,
                "failed_files": [],
                "has_duplicates": False
            }
            return jsonify(res_payload), 201

        has_duplicates = any(f.get("is_duplicate") for f in failed_files)

        if not successful_batches and failed_files:
            # If failed files are duplicate files, return 200 with structured duplicate payload
            # so the browser client doesn't log a 400 Bad Request network failure.
            if has_duplicates:
                return jsonify({
                    "success": False,
                    "is_duplicate": True,
                    "detail": failed_files[0]["error"],
                    "failed_files": failed_files,
                    "batches": [],
                    "total_files": len(uploaded_files),
                    "successful_count": 0
                }), 200

            return jsonify({
                "detail": failed_files[0]["error"],
                "failed_files": failed_files
            }), 400

        return jsonify({
            "success": True,
            "batches": successful_batches,
            "total_files": len(uploaded_files),
            "successful_count": len(successful_batches),
            "failed_files": failed_files,
            "has_duplicates": has_duplicates
        }), 201

    except Exception as global_err:
        import traceback
        traceback.print_exc()
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({
            "detail": f"Server error: {str(global_err)}",
            "failed_files": [{"filename": "upload", "error": str(global_err), "is_duplicate": False}]
        }), 500
    finally:
        db.close()


def scan_input_folder():
    """Scans the active tenant company's input directory for new statement files (.xlsx, .xls, .csv, .pdf, .txt)."""
    valid_exts = (".xlsx", ".xls", ".csv", ".pdf", ".txt")
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        company_input_dir = config.get_company_input_dir(company_id)
        workflow = WorkflowService(db)
        processed_batches = []

        files = [
            f for f in os.listdir(company_input_dir)
            if f.lower().endswith(valid_exts) and not f.startswith("~$")
        ]
        for filename in files:
            full_path = os.path.join(company_input_dir, filename)
            try:
                batch = workflow.ingest_excel_file(full_path, filename, company_id=company_id)
                processed_batches.append(ImportBatchOut.model_validate(batch).model_dump(mode="json"))
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        return jsonify(processed_batches)
    finally:
        db.close()


def list_documents():
    """Lists uploaded documents for the active tenant company from the documents table."""
    limit = request.args.get("limit", default=50, type=int)
    doc_type = request.args.get("document_type")
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = DocumentRepository(db)
        docs = repo.list_by_company(company_id=company_id, limit=limit, document_type=doc_type)
        return jsonify([
            {
                "id": d.id,
                "company_id": d.company_id,
                "document_type": d.document_type,
                "filename": d.filename,
                "file_path": d.file_path,
                "file_hash": d.file_hash,
                "file_size_bytes": d.file_size_bytes,
                "mime_type": d.mime_type,
                "uploaded_by": d.uploaded_by,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ])
    finally:
        db.close()


def list_batches():
    """Lists recent imported batches for the active tenant company."""
    limit = request.args.get("limit", default=50, type=int)
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = BatchRepository(db)
        batches = repo.list_recent(company_id=company_id, limit=limit)
        return jsonify([ImportBatchOut.model_validate(b).model_dump() for b in batches])
    finally:
        db.close()


def get_batch(batch_id: int):
    """Retrieves a specific import batch by database ID."""
    db = SessionLocal()
    try:
        repo = BatchRepository(db)
        batch = repo.get_by_id(batch_id)
        if not batch:
            return jsonify({"detail": "Batch not found"}), 404
        return jsonify(ImportBatchOut.model_validate(batch).model_dump())
    finally:
        db.close()
