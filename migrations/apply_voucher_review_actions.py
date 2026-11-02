import sys
from pathlib import Path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from database.dbConnection import SessionLocal
from sqlalchemy import text

def run():
    db = SessionLocal()
    try:
        print("Checking database columns and ENUM status...")
        cols_bt = [r[0] for r in db.execute(text("DESCRIBE bank_transactions")).fetchall()]
        cols_v = [r[0] for r in db.execute(text("DESCRIBE vouchers")).fetchall()]
        v_status = db.execute(text("SHOW COLUMNS FROM vouchers LIKE 'status'")).fetchall()[0][1]

        print(f"bank_transactions has rejection_reason: {'rejection_reason' in cols_bt}")
        print(f"vouchers has rejection_reason: {'rejection_reason' in cols_v}")
        print(f"vouchers status column: {v_status}")

        if "REJECTED" not in v_status:
            print("Updating vouchers.status ENUM...")
            db.execute(text("ALTER TABLE vouchers MODIFY COLUMN status ENUM('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'POSTED', 'REVERSED', 'CANCELLED', 'REJECTED', 'HOLD') NOT NULL DEFAULT 'DRAFT'"))

        if "rejection_reason" not in cols_v:
            print("Adding vouchers.rejection_reason...")
            db.execute(text("ALTER TABLE vouchers ADD COLUMN rejection_reason TEXT NULL AFTER narration"))

        if "rejection_reason" not in cols_bt:
            print("Adding bank_transactions.rejection_reason...")
            db.execute(text("ALTER TABLE bank_transactions ADD COLUMN rejection_reason TEXT NULL AFTER skip_reason"))

        db.commit()
        print(">>> ALL DATABASE MIGRATIONS READY AND VERIFIED! <<<")
    except Exception as e:
        db.rollback()
        print(f"Migration error: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    run()

