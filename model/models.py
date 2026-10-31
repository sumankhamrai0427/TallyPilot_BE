import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean,
    DateTime, ForeignKey, JSON, Date, Enum, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship
from database.dbConnection import Base


# ============================================================================
# ENUMS
# ============================================================================
class TransactionStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    CLASSIFIED = "CLASSIFIED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTING = "SUBMITTING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class VoucherType(str, enum.Enum):
    PAYMENT = "Payment"
    RECEIPT = "Receipt"
    CONTRA = "Contra"
    JOURNAL = "Journal"
    SALES = "Sales"
    PURCHASE = "Purchase"


class VoucherStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class AccountGroupType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class AccountNature(str, enum.Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class PartyType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    VENDOR = "VENDOR"
    BOTH = "BOTH"


class DocumentType(str, enum.Enum):
    INVOICE = "INVOICE"
    RECEIPT = "RECEIPT"
    BANK_STATEMENT = "BANK_STATEMENT"
    PAYMENT_VOUCHER = "PAYMENT_VOUCHER"
    SUPPORTING_DOC = "SUPPORTING_DOC"
    OTHER = "OTHER"


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class ReconciliationStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    LOCKED = "LOCKED"


class ReconciliationMatchType(str, enum.Enum):
    EXACT = "EXACT"
    MULTI = "MULTI"
    MANUAL = "MANUAL"
    PARTIAL = "PARTIAL"


class ReconciliationMatchStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    DISCREPANCY = "DISCREPANCY"


# ============================================================================
# 1. APPLICATION SETTINGS
# ============================================================================
class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============================================================================
# 2. MULTI-TENANT COMPANY & FINANCIAL PERIODS
# ============================================================================
class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    code = Column(String(32), unique=True, nullable=False)
    pan = Column(String(16), nullable=True)
    gstin = Column(String(32), nullable=True)
    financial_year_start_month = Column(Integer, default=4, nullable=False)
    currency = Column(String(8), default="INR", nullable=False)
    tally_company_name = Column(String(255), nullable=True)
    tally_url = Column(String(255), default="http://localhost:9000", nullable=True)
    default_bank_ledger = Column(String(255), default="HDFC Bank", nullable=True)
    tally_simulation_mode = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    financial_years = relationship("FinancialYear", back_populates="company", cascade="all, delete-orphan")
    account_groups = relationship("AccountGroup", back_populates="company", cascade="all, delete-orphan")
    ledger_accounts = relationship("LedgerAccount", back_populates="company", cascade="all, delete-orphan")
    parties = relationship("Party", back_populates="company", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="company", cascade="all, delete-orphan")
    vouchers = relationship("Voucher", back_populates="company", cascade="all, delete-orphan")


class FinancialYear(Base):
    __tablename__ = "financial_years"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    fy_code = Column(String(32), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_current = Column(Boolean, default=True, nullable=True)
    is_closed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="financial_years")
    vouchers = relationship("Voucher", back_populates="financial_year")


# ============================================================================
# 3. CHART OF ACCOUNTS & PARTIES
# ============================================================================
class AccountGroup(Base):
    __tablename__ = "account_groups"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(64), nullable=True)
    parent_id = Column(Integer, nullable=True)
    group_type = Column(String(16), nullable=False)  # ASSET, LIABILITY, EQUITY, INCOME, EXPENSE
    nature = Column(String(8), nullable=False)       # DEBIT, CREDIT
    affects_gross_profit = Column(Boolean, default=False, nullable=False)
    is_builtin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="account_groups")
    ledgers = relationship("LedgerAccount", back_populates="group")


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey("account_groups.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(64), nullable=True)
    opening_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    current_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    is_subledger = Column(Boolean, default=False, nullable=False)
    parent_ledger_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="ledger_accounts")
    group = relationship("AccountGroup", back_populates="ledgers")
    party = relationship("Party", back_populates="ledger", uselist=False)


class Party(Base):
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    party_type = Column(String(16), nullable=False)  # CUSTOMER, VENDOR, BOTH
    gstin = Column(String(32), nullable=True)
    pan = Column(String(16), nullable=True)
    credit_limit = Column(Numeric(15, 2), default=0.00, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="parties")
    ledger = relationship("LedgerAccount", back_populates="party")


# ============================================================================
# 4. DOCUMENTS REPOSITORY
# ============================================================================
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_type = Column(String(32), nullable=False)  # INVOICE, RECEIPT, BANK_STATEMENT, etc.
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String(128), nullable=True)
    uploaded_by = Column(String(128), default="SYSTEM", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="documents")


# ============================================================================
# 5. BANK INGESTION & TRANSACTIONS
# ============================================================================
class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    fy_id = Column(Integer, ForeignKey("financial_years.id", ondelete="RESTRICT"), nullable=False)
    batch_id = Column(String(64), unique=True, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=False)
    total_rows = Column(Integer, default=0)
    parsed_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    status = Column(String(32), default="PENDING", index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    transactions = relationship("BankTransaction", back_populates="batch", cascade="all, delete-orphan")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=False, index=True)
    bank_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    source_row_index = Column(Integer, nullable=False)
    transaction_date = Column(Date, nullable=False, index=True)
    value_date = Column(Date, nullable=True)
    bank_reference = Column(String(128), nullable=True, index=True)
    cheque_number = Column(String(64), nullable=True)
    narration = Column(Text, nullable=False)
    debit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    credit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    balance = Column(Numeric(15, 2), nullable=True)
    status = Column(String(32), default=TransactionStatus.RECEIVED.value, nullable=False, index=True)
    requires_review = Column(Boolean, default=False, nullable=False)
    is_skipped = Column(Boolean, default=False, nullable=False)
    skip_reason = Column(Text, nullable=True)
    reconciliation_status = Column(String(32), default="UNRECONCILED", nullable=False)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    batch = relationship("ImportBatch", back_populates="transactions")
    classification = relationship("TransactionClassification", back_populates="transaction", uselist=False, cascade="all, delete-orphan")
    reviews = relationship("HumanReview", back_populates="transaction", cascade="all, delete-orphan")
    approvals = relationship("ApprovalRecord", back_populates="transaction", cascade="all, delete-orphan")
    submissions = relationship("TallySubmission", back_populates="transaction", cascade="all, delete-orphan")

    @property
    def amount(self):
        return self.debit_amount if (self.debit_amount or 0) > 0 else (self.credit_amount or 0)

    @property
    def transaction_type(self):
        return "DEBIT" if (self.debit_amount or 0) > 0 else "CREDIT"

    @property
    def suggested_ledger(self):
        if self.classification:
            return self.classification.suggested_ledger
        return None


# ============================================================================
# 6. AI CLASSIFICATIONS & HUMAN REVIEWS
# ============================================================================
class TransactionClassification(Base):
    __tablename__ = "transaction_classifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=False, index=True)
    model_name = Column(String(128), nullable=False)
    transaction_type = Column(String(64), nullable=False)
    suggested_voucher_type = Column(String(32), nullable=False)
    suggested_ledger = Column(String(255), nullable=True)
    suggested_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    contra_ledger = Column(String(255), nullable=True)
    contra_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    confidence = Column(Numeric(5, 4), nullable=False)
    explanation = Column(Text, nullable=True)
    ambiguity_reason = Column(Text, nullable=True)
    requires_human_review = Column(Boolean, default=True, nullable=False)
    is_fallback_rule = Column(Boolean, default=False, nullable=False)
    raw_ai_response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    transaction = relationship("BankTransaction", back_populates="classification")


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_user = Column(String(128), default="system_user", nullable=False)
    corrected_transaction_type = Column(String(64), nullable=False)
    corrected_voucher_type = Column(String(32), nullable=False)
    selected_ledger = Column(String(255), nullable=False)
    selected_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    contra_ledger = Column(String(255), nullable=True)
    contra_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    resolution_action = Column(String(32), default="SUBMIT_CORRECTION", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    transaction = relationship("BankTransaction", back_populates="reviews")


# ============================================================================
# 7. DOUBLE-ENTRY VOUCHERS & LINES
# ============================================================================
class Voucher(Base):
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    fy_id = Column(Integer, ForeignKey("financial_years.id", ondelete="RESTRICT"), nullable=False)
    voucher_number = Column(String(64), nullable=False)
    voucher_type = Column(String(32), nullable=False)  # Payment, Receipt, Contra, Journal, Sales, Purchase
    voucher_date = Column(Date, nullable=False, index=True)
    total_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    narration = Column(Text, nullable=True)
    bank_transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=True)
    source_document_id = Column(Integer, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True)
    status = Column(String(32), default=VoucherStatus.DRAFT.value, nullable=False, index=True)
    created_by = Column(String(128), default="SYSTEM", nullable=False)
    posted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="vouchers")
    financial_year = relationship("FinancialYear", back_populates="vouchers")
    bank_transaction = relationship("BankTransaction", foreign_keys=[bank_transaction_id])
    source_document = relationship("Document", foreign_keys=[source_document_id])
    lines = relationship("VoucherLine", back_populates="voucher", cascade="all, delete-orphan")
    approvals = relationship("VoucherApproval", back_populates="voucher", cascade="all, delete-orphan")


class VoucherLine(Base):
    __tablename__ = "voucher_lines"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=False, index=True)
    line_number = Column(Integer, nullable=False)
    ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    party_id = Column(Integer, nullable=True)
    debit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    credit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    narration = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    voucher = relationship("Voucher", back_populates="lines")
    ledger = relationship("LedgerAccount", foreign_keys=[ledger_id])
    party = relationship("Party", primaryjoin="foreign(VoucherLine.party_id) == Party.id")


class VoucherApproval(Base):
    __tablename__ = "voucher_approvals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=False, index=True)
    approver_user = Column(String(128), nullable=False)
    action = Column(String(32), nullable=False)  # APPROVED, REJECTED, REQUEST_CHANGE
    approval_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    voucher = relationship("Voucher", back_populates="approvals")


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=False, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=True)
    approver_user = Column(String(128), default="finance_admin", nullable=False)
    voucher_type = Column(String(32), nullable=False)
    primary_ledger = Column(String(255), nullable=False)
    primary_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    contra_ledger = Column(String(255), nullable=False)
    contra_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    amount = Column(Numeric(15, 2), nullable=False)
    approval_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    transaction = relationship("BankTransaction", back_populates="approvals")


# ============================================================================
# 8. IMMUTABLE GENERAL LEDGER
# ============================================================================
class GeneralLedger(Base):
    __tablename__ = "general_ledger"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    fy_id = Column(Integer, ForeignKey("financial_years.id", ondelete="RESTRICT"), nullable=False)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=False, index=True)
    voucher_line_id = Column(Integer, ForeignKey("voucher_lines.id", ondelete="RESTRICT"), unique=True, nullable=False)
    posting_date = Column(Date, nullable=False, index=True)
    ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    debit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    credit_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    running_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    is_reversed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    voucher = relationship("Voucher", foreign_keys=[voucher_id])
    ledger = relationship("LedgerAccount", foreign_keys=[ledger_id])
    line = relationship("VoucherLine", foreign_keys=[voucher_line_id])


# ============================================================================
# 9. BANK RECONCILIATION
# ============================================================================
class BankReconciliation(Base):
    __tablename__ = "bank_reconciliations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    bank_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False)
    statement_start_date = Column(Date, nullable=False)
    statement_end_date = Column(Date, nullable=False)
    statement_closing_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    book_closing_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    reconciled_balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    status = Column(String(32), default=ReconciliationStatus.OPEN.value, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    items = relationship("BankReconciliationItem", back_populates="reconciliation", cascade="all, delete-orphan")


class BankReconciliationItem(Base):
    __tablename__ = "bank_reconciliation_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reconciliation_id = Column(Integer, ForeignKey("bank_reconciliations.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    bank_transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=False)
    voucher_line_id = Column(Integer, ForeignKey("voucher_lines.id", ondelete="RESTRICT"), nullable=True)
    match_type = Column(String(32), default=ReconciliationMatchType.EXACT.value, nullable=False)
    matched_amount = Column(Numeric(15, 2), default=0.00, nullable=False)
    status = Column(String(32), default=ReconciliationMatchStatus.MATCHED.value, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    reconciliation = relationship("BankReconciliation", back_populates="items")


# ============================================================================
# 10. TALLY PRIME INTEGRATION & AUDIT LOGS
# ============================================================================
class TallyLedger(Base):
    __tablename__ = "tally_ledgers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    parent_group = Column(String(255), nullable=False, index=True)
    guid = Column(String(128), nullable=True)
    internal_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    sync_status = Column(String(32), default="SYNCED", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LedgerMapping(Base):
    __tablename__ = "ledger_mappings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    keyword_pattern = Column(String(255), nullable=False, index=True)
    target_ledger = Column(String(255), nullable=False)
    target_ledger_id = Column(Integer, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True)
    voucher_type = Column(String(32), default="Payment", nullable=False)
    confidence_boost = Column(Numeric(5, 4), default=1.0000, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TallySubmission(Base):
    __tablename__ = "tally_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="RESTRICT"), nullable=True, index=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="RESTRICT"), nullable=True, index=True)
    company_name = Column(String(255), nullable=False)
    voucher_type = Column(String(32), nullable=False)
    voucher_date = Column(Date, nullable=False)
    payload_hash = Column(String(64), nullable=False, index=True)
    xml_payload = Column(Text, nullable=False)
    tally_response_raw = Column(Text, nullable=True)
    tally_voucher_guid = Column(String(128), nullable=True)
    status = Column(String(32), default="SUBMITTING", nullable=False, index=True)
    http_status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    transaction = relationship("BankTransaction", back_populates="submissions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor = Column(String(128), default="SYSTEM", nullable=False)
    action = Column(String(64), nullable=False, index=True)
    batch_id = Column(Integer, nullable=True, index=True)
    transaction_id = Column(Integer, nullable=True, index=True)
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=True)
    summary = Column(String(500), nullable=False)
    details = Column(JSON, nullable=True)


# ============================================================================
# 11. AI CONVERSATIONAL ASSISTANT (HLA Part 8.2 & Part 12)
# ============================================================================
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = Column(String(255), default="New Accounting Session", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sender = Column(String(32), nullable=False)  # USER, ASSISTANT, SYSTEM
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)     # Tool call metadata or results
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")
