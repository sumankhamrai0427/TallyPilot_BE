import time
import os
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from utils.config import config
from database.dbConnection import SessionLocal
from helper.workflow_service import WorkflowService


class BankStatementFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filename = os.path.basename(event.src_path)
        if filename.lower().endswith((".xlsx", ".xls", ".csv")) and not filename.startswith("~$"):
            print(f"[Watcher] New bank statement detected: {filename}")
            # Try to extract company_id from path (.../companies/<company_id>/input/...)
            company_id = None
            parts = os.path.normpath(event.src_path).split(os.sep)
            if "companies" in parts:
                idx = parts.index("companies")
                if idx + 1 < len(parts):
                    try:
                        company_id = int(parts[idx + 1])
                    except ValueError:
                        company_id = None

            time.sleep(1.0)
            db = SessionLocal()
            try:
                workflow = WorkflowService(db)
                workflow.ingest_excel_file(event.src_path, filename, company_id=company_id)
                print(f"[Watcher] Successfully processed: {filename} (Company: {company_id or 'default'})")
            except Exception as e:
                print(f"[Watcher] Processing error for {filename}: {e}")
            finally:
                db.close()


def start_folder_watcher():
    os.makedirs(config.STORAGE_DIR, exist_ok=True)
    event_handler = BankStatementFileHandler()
    observer = Observer()
    observer.schedule(event_handler, path=config.STORAGE_DIR, recursive=True)
    observer.start()
    print(f"[Watcher] Monitoring storage tree '{config.STORAGE_DIR}' for new statements (.xlsx, .xls, .csv)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    start_folder_watcher()

