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
    """Uploads and ingests a bank statement file (.xlsx, .xls, .csv)."""
    if "file" not in request.files:
        return jsonify({"detail": "No file uploaded in form field 'file'"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"detail": "Empty file name provided"}), 400

    ext = os.path.splitext(uploaded_file.filename)[1].lower()
    if ext not in [".xlsx", ".xls", ".csv"]:
        return jsonify({"detail": "Invalid file format. Supported formats: .xlsx, .xls, .csv"}), 400

    os.makedirs(config.INPUT_DIR, exist_ok=True)
    destination_path = os.path.join(config.INPUT_DIR, uploaded_file.filename)

    uploaded_file.save(destination_path)

    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        batch = workflow.ingest_excel_file(destination_path, uploaded_file.filename)
        return jsonify(ImportBatchOut.model_validate(batch).model_dump()), 201
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        return jsonify({"detail": f"File processing error: {str(e)}"}), 500
    finally:
        db.close()


def scan_input_folder():
    """Scans the configured input directory for new statement files (.xlsx, .xls, .csv)."""
    os.makedirs(config.INPUT_DIR, exist_ok=True)
    db = SessionLocal()
    try:
        workflow = WorkflowService(db)
        processed_batches = []

        files = [
            f for f in os.listdir(config.INPUT_DIR)
            if f.lower().endswith((".xlsx", ".xls", ".csv")) and not f.startswith("~$")
        ]
        for filename in files:
            full_path = os.path.join(config.INPUT_DIR, filename)
            try:
                batch = workflow.ingest_excel_file(full_path, filename)
                processed_batches.append(ImportBatchOut.model_validate(batch).model_dump())
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
