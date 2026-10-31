import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

from database.dbConnection import SessionLocal
from sqlalchemy import text

def run_migration():
    db = SessionLocal()
    try:
        print("Checking existing columns in companies table...")
        cols = [r[0] for r in db.execute(text("DESCRIBE companies")).fetchall()]
        print(f"Existing columns: {cols}")

        if "tally_company_name" not in cols:
            print("Adding tally_company_name...")
            db.execute(text("ALTER TABLE companies ADD COLUMN tally_company_name VARCHAR(255) NULL AFTER currency"))

        if "tally_url" not in cols:
            print("Adding tally_url...")
            db.execute(text("ALTER TABLE companies ADD COLUMN tally_url VARCHAR(255) NULL DEFAULT 'http://localhost:9000' AFTER tally_company_name"))

        if "default_bank_ledger" not in cols:
            print("Adding default_bank_ledger...")
            db.execute(text("ALTER TABLE companies ADD COLUMN default_bank_ledger VARCHAR(255) NULL DEFAULT 'HDFC Bank' AFTER tally_url"))

        if "tally_simulation_mode" not in cols:
            print("Adding tally_simulation_mode...")
            db.execute(text("ALTER TABLE companies ADD COLUMN tally_simulation_mode TINYINT(1) NOT NULL DEFAULT 1 AFTER default_bank_ledger"))

        db.commit()

        print("Populating Demo Company with initial credentials...")
        db.execute(text("""
            UPDATE companies 
            SET tally_company_name = 'Demo Company (FY 2026-27)',
                tally_url = 'http://localhost:9000',
                default_bank_ledger = 'HDFC Bank',
                tally_simulation_mode = 1
            WHERE id = 1
        """))
        db.commit()

        print("\n=== Updated companies table columns ===")
        for r in db.execute(text("DESCRIBE companies")).fetchall():
            print(r)

        print("\n=== Demo Company updated record ===")
        for r in db.execute(text("SELECT id, name, code, pan, gstin, currency, tally_company_name, tally_url, default_bank_ledger, tally_simulation_mode FROM companies")).fetchall():
            print(r)

        print("\n>>> MIGRATION SUCCESSFUL! <<<")
    except Exception as e:
        db.rollback()
        print(f"Error during migration: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()

