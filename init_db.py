import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.core.config import settings
from app.database.session import engine, Base, SessionLocal
from app.repositories.ledger_repository import LedgerRepository

def init_database():
    print(f"Connecting to database: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")
    print("Creating all tables from SQLAlchemy models...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")

    print("Checking initial Tally Ledgers...")
    db = SessionLocal()
    try:
        repo = LedgerRepository(db)
        default_ledgers = [
            ("HDFC Bank", "Bank Accounts"),
            ("State Bank of India", "Bank Accounts"),
            ("ABC Suppliers Ltd", "Sundry Creditors"),
            ("Apex Technologies", "Sundry Creditors"),
            ("Global Logistics Corp", "Sundry Creditors"),
            ("Zentec Solutions Pvt Ltd", "Sundry Creditors"),
            ("Acme Retail Customers", "Sundry Debtors"),
            ("National Enterprises", "Sundry Debtors"),
            ("Electricity Expenses", "Indirect Expenses"),
            ("Office Rent", "Indirect Expenses"),
            ("Telephone & Internet Charges", "Indirect Expenses"),
            ("Printing & Stationery", "Indirect Expenses"),
            ("Bank Charges", "Indirect Expenses"),
            ("Professional Fees", "Indirect Expenses"),
            ("Sales Account", "Sales Accounts"),
            ("Purchase Account", "Purchase Accounts")
        ]
        for name, group in default_ledgers:
            repo.upsert(name, group)
        print("Tally master ledgers initialized.")
    finally:
        db.close()

    print("Initialization complete! You are ready to start TallyPilot.")

if __name__ == "__main__":
    init_database()

