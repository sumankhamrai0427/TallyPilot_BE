import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean,
    DateTime, ForeignKey, JSON, Date, Enum
)
from sqlalchemy.orm import relationship
from database.dbConnection import Base


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


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
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


class TallyLedger(Base):
    __tablename__ = "tally_ledgers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    parent_group = Column(String(255), nullable=False, index=True)
    guid = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False, index=True)
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
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    batch = relationship("ImportBatch", back_populates="transactions")
    classification = relationship("TransactionClassification", back_populates="transaction", uselist=False, cascade="all, delete-orphan")
    reviews = relationship("HumanReview", back_populates="transaction", cascade="all, delete-orphan")
    approvals = relationship("ApprovalRecord", back_populates="transaction", cascade="all, delete-orphan")
    submissions = relationship("TallySubmission", back_populates="transaction", cascade="all, delete-orphan")


class TransactionClassification(Base):
    __tablename__ = "transaction_classifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    model_name = Column(String(128), nullable=False)
    transaction_type = Column(String(64), nullable=False)
    suggested_voucher_type = Column(String(32), nullable=False)
    suggested_ledger = Column(String(255), nullable=True)
    contra_ledger = Column(String(255), nullable=True)
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
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_user = Column(String(128), default="system_user", nullable=False)
    corrected_transaction_type = Column(String(64), nullable=False)
    corrected_voucher_type = Column(String(32), nullable=False)
    selected_ledger = Column(String(255), nullable=False)
    contra_ledger = Column(String(255), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    resolution_action = Column(String(32), default="SUBMIT_CORRECTION", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    transaction = relationship("BankTransaction", back_populates="reviews")


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_user = Column(String(128), default="finance_admin", nullable=False)
    voucher_type = Column(String(32), nullable=False)
    primary_ledger = Column(String(255), nullable=False)
    contra_ledger = Column(String(255), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    approval_notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    transaction = relationship("BankTransaction", back_populates="approvals")


class TallySubmission(Base):
    __tablename__ = "tally_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
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


class LedgerMapping(Base):
    __tablename__ = "ledger_mappings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    keyword_pattern = Column(String(255), unique=True, nullable=False, index=True)
    target_ledger = Column(String(255), nullable=False)
    voucher_type = Column(String(32), default="Payment", nullable=False)
    confidence_boost = Column(Numeric(5, 4), default=1.0000, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor = Column(String(128), default="SYSTEM", nullable=False)
    action = Column(String(64), nullable=False, index=True)
    batch_id = Column(Integer, nullable=True, index=True)
    transaction_id = Column(Integer, nullable=True, index=True)
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=True)
    summary = Column(String(500), nullable=False)
    details = Column(JSON, nullable=True)


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

