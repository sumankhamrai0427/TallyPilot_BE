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
from database.repositories import BatchRepository
from model.schemas import ImportBatchOut


def upload_bank_statement():
    """Uploads and ingests one or multiple bank statement files (.xlsx, .xls, .csv, .pdf, .txt)."""
    # Collect files from 'files' or 'file' form fields
    uploaded_files = request.files.getlist("files")
    if not uploaded_files or (len(uploaded_files) == 1 and not uploaded_files[0].filename):
        uploaded_files = request.files.getlist("file")

    if not uploaded_files or not any(f.filename for f in uploaded_files):
        return jsonify({"detail": "No files uploaded. Provide file(s) in form field 'files' or 'file'"}), 400

    valid_extensions = [".xlsx", ".xls", ".csv", ".pdf", ".txt"]
    os.makedirs(config.INPUT_DIR, exist_ok=True)

    successful_batches = []
    failed_files = []

    db = SessionLocal()
    try:
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

            destination_path = os.path.join(config.INPUT_DIR, filename)
            try:
                uploaded_file.save(destination_path)
                batch = workflow.ingest_excel_file(destination_path, filename)
                batch_dict = ImportBatchOut.model_validate(batch).model_dump(mode="json")
                successful_batches.append(batch_dict)
            except ValueError as ve:
                failed_files.append({"filename": filename, "error": str(ve)})
            except Exception as e:
                failed_files.append({"filename": filename, "error": f"Processing error: {str(e)}"})

        # Backward compatibility for single file upload
        if len(uploaded_files) == 1 and len(successful_batches) == 1 and not failed_files:
            single_res = successful_batches[0]
            single_res["batches"] = successful_batches
            return jsonify(single_res), 201

        if not successful_batches and failed_files:
            return jsonify({
                "detail": failed_files[0]["error"],
                "failed_files": failed_files
            }), 400

        return jsonify({
            "batches": successful_batches,
            "total_files": len(uploaded_files),
            "successful_count": len(successful_batches),
            "failed_files": failed_files
        }), 201

    finally:
        db.close()


def scan_input_folder():
    """Scans the configured input directory for new statement files (.xlsx, .xls, .csv, .pdf, .txt)."""
    os.makedirs(config.INPUT_DIR, exist_ok=True)
    valid_exts = (".xlsx", ".xls", ".csv", ".pdf", ".txt")
    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        processed_batches = []

        files = [
            f for f in os.listdir(config.INPUT_DIR)
            if f.lower().endswith(valid_exts) and not f.startswith("~$")
        ]
        for filename in files:
            full_path = os.path.join(config.INPUT_DIR, filename)
            try:
                batch = workflow.ingest_excel_file(full_path, filename)
                processed_batches.append(ImportBatchOut.model_validate(batch).model_dump(mode="json"))
            except Exception:
                continue

        return jsonify(processed_batches)
    finally:
        db.close()


def list_batches():
    """Lists recent imported batches."""
    limit = request.args.get("limit", default=50, type=int)
    db = SessionLocal()
    try:
        repo = BatchRepository(db)
        batches = repo.list_recent(limit=limit)
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
