"""Reset all transaction tables for fresh end-to-end testing.
Keeps master tables intact (Companies, FYs, Chart of Accounts, Ledgers, Parties, Settings).
Resets ledger account current balances back to their opening balances.

Run from terminal:
    python backend/scripts/reset_transactions.py
or
    backend\\venv\\Scripts\\python.exe backend/scripts/reset_transactions.py
"""
import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from database.dbConnection import engine, SessionLocal
from utils.logger import logger


TRANSACTIONAL_TABLES = [
    "chat_messages",
    "chat_sessions",
    "audit_logs",
    "tally_submissions",
    "bank_reconciliation_items",
    "bank_reconciliations",
    "general_ledger",
    "voucher_approvals",
    "voucher_lines",
    "vouchers",
    "approval_records",
    "human_reviews",
    "transaction_classifications",
    "bank_transactions",
    "documents",
    "import_batches",
]


def reset_transactions():
    print("=" * 65)
    print("  TallyPilot V2 - Reset All Transactions for Fresh Testing")
    print("=" * 65)

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            print("\n[1/3] Disabling foreign key constraints...")
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))

            print("[2/3] Truncating transactional tables:")
            for tbl in TRANSACTIONAL_TABLES:
                try:
                    conn.execute(text(f"TRUNCATE TABLE `{tbl}`;"))
                    print(f"   ✓ Truncated `{tbl}`")
                except Exception as ex:
                    print(f"   ⚠ Notice for `{tbl}`: {ex}")

            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

            print("\n[3/3] Resetting Ledger Account balances...")
            conn.execute(text("UPDATE ledger_accounts SET current_balance = opening_balance;"))
            print("   ✓ Ledger accounts current_balance restored to opening_balance")

            trans.commit()
            print("\n" + "=" * 65)
            print("  SUCCESS: Database is now completely fresh for testing!")
            print("  - All uploaded files, batches, and transactions cleared.")
            print("  - All proposed and posted vouchers cleared.")
            print("  - All General Ledger postings cleared.")
            print("  - Master Chart of Accounts, Companies & Parties PRESERVED.")
            print("=" * 65 + "\n")
        except Exception as e:
            trans.rollback()
            print(f"\n❌ ERROR during reset: {e}")
            sys.exit(1)


if __name__ == "__main__":
    reset_transactions()

