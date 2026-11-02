"""Database migration to align with HLA Section 7 (Vouchers) and Section 10 (Reporting Engine).
Expands voucher types to 13 types, adds reversal audit columns, and adds cost centre / tax columns.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database.dbConnection import SessionLocal

def run_migration():
    db = SessionLocal()
    try:
        print("Checking and applying HLA Section 7 & 10 database changes...")

        # 1. Expand vouchers.voucher_type to 13 types
        print("1. Expanding vouchers.voucher_type ENUM to 13 types...")
        db.execute(text("""
            ALTER TABLE vouchers MODIFY COLUMN voucher_type ENUM(
                'Payment', 'Receipt', 'Contra', 'Journal', 'Purchase', 'Sales',
                'Debit Note', 'Credit Note', 'Payroll', 'Opening Balance',
                'Fixed Asset', 'Depreciation', 'Adjustment'
            ) NOT NULL DEFAULT 'Journal';
        """))
        print("   -> Voucher types expanded successfully.")

        # 2. Add reversal tracking columns to vouchers table
        print("2. Checking reversal audit columns in vouchers table...")
        columns_vouchers = [row[0] for row in db.execute(text("SHOW COLUMNS FROM vouchers;")).fetchall()]

        if "reversal_voucher_id" not in columns_vouchers:
            db.execute(text("""
                ALTER TABLE vouchers ADD COLUMN reversal_voucher_id INT NULL AFTER status;
            """))
            print("   -> Added reversal_voucher_id")

        if "reversed_at" not in columns_vouchers:
            db.execute(text("""
                ALTER TABLE vouchers ADD COLUMN reversed_at DATETIME NULL AFTER posted_at;
            """))
            print("   -> Added reversed_at")

        if "reversal_reason" not in columns_vouchers:
            db.execute(text("""
                ALTER TABLE vouchers ADD COLUMN reversal_reason VARCHAR(255) NULL AFTER reversal_voucher_id;
            """))
            print("   -> Added reversal_reason")

        # 3. Add cost_centre, tax_code, party_reference to voucher_lines
        print("3. Checking line items columns in voucher_lines table...")
        columns_lines = [row[0] for row in db.execute(text("SHOW COLUMNS FROM voucher_lines;")).fetchall()]

        if "cost_centre" not in columns_lines:
            db.execute(text("""
                ALTER TABLE voucher_lines ADD COLUMN cost_centre VARCHAR(100) NULL AFTER narration;
            """))
            print("   -> Added cost_centre to voucher_lines")

        if "tax_code" not in columns_lines:
            db.execute(text("""
                ALTER TABLE voucher_lines ADD COLUMN tax_code VARCHAR(50) NULL AFTER cost_centre;
            """))
            print("   -> Added tax_code to voucher_lines")

        if "party_reference" not in columns_lines:
            db.execute(text("""
                ALTER TABLE voucher_lines ADD COLUMN party_reference VARCHAR(100) NULL AFTER tax_code;
            """))
            print("   -> Added party_reference to voucher_lines")

        db.commit()
        print("All database migrations for HLA Section 7 & 10 applied successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error executing migration: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()

