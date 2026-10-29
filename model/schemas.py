from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from model.models import TransactionStatus, VoucherType

# AI Structured Output Schema
class AICorrectionProposal(BaseModel):
    transaction_type: str = Field(..., description="E.g., supplier_payment, customer_receipt, bank_charges, contra_transfer, salary_payment")
    suggested_voucher_type: VoucherType = Field(..., description="Payment, Receipt, Contra, or Journal")
    suggested_ledger: Optional[str] = Field(None, description="Exact matching ledger from supplied Tally ledgers")
    contra_ledger: Optional[str] = Field(None, description="Bank or cash ledger name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence estimate between 0.0 and 1.0")
    requires_human_review: bool = Field(True, description="True if uncertain or requires verification")
    ambiguity_reason: Optional[str] = Field(None, description="Explanation why clarification is required")
    explanation: Optional[str] = Field(None, description="Concise rationale for suggestion")


# Transaction schemas
class BankTransactionBase(BaseModel):
    source_row_index: int
    transaction_date: date
    value_date: Optional[date] = None
    bank_reference: Optional[str] = None
    cheque_number: Optional[str] = None
    narration: str
    debit_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    credit_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    balance: Optional[Decimal] = None


class TransactionClassificationOut(BaseModel):
    id: int
    model_name: str
    transaction_type: str
    suggested_voucher_type: str
    suggested_ledger: Optional[str]
    contra_ledger: Optional[str]
    confidence: float
    explanation: Optional[str]
    ambiguity_reason: Optional[str]
    requires_human_review: bool
    is_fallback_rule: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HumanReviewOut(BaseModel):
    id: int
    reviewer_user: str
    corrected_transaction_type: str
    corrected_voucher_type: str
    selected_ledger: str
    contra_ledger: Optional[str]
    reviewer_notes: Optional[str]
    resolution_action: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankTransactionOut(BaseModel):
    id: int
    batch_id: int
    source_row_index: int
    transaction_date: date
    value_date: Optional[date]
    bank_reference: Optional[str]
    cheque_number: Optional[str]
    narration: str
    debit_amount: Decimal
    credit_amount: Decimal
    balance: Optional[Decimal]
    status: str
    requires_review: bool
    is_skipped: bool
    skip_reason: Optional[str]
    created_at: datetime
    classification: Optional[TransactionClassificationOut] = None
    reviews: List[HumanReviewOut] = []

    model_config = ConfigDict(from_attributes=True)


# Human Clarification Request
class ClarifyTransactionRequest(BaseModel):
    selected_ledger: str = Field(..., min_length=1, description="Chosen Tally ledger name")
    corrected_voucher_type: VoucherType = Field(..., description="Voucher type (Payment, Receipt, Contra, Journal)")
    corrected_transaction_type: str = Field(..., min_length=1, description="Category classification")
    reviewer_notes: Optional[str] = Field(None, description="Optional notes from accountant")
    resolution_action: str = Field(default="SUBMIT_CORRECTION")


# Skip Transaction Request
class SkipTransactionRequest(BaseModel):
    reason: str = Field(..., min_length=2, description="Reason for skipping this transaction")


# Approval Request
class ApproveTransactionRequest(BaseModel):
    approver_user: str = Field(default="finance_admin")
    voucher_type: Optional[VoucherType] = None
    primary_ledger: Optional[str] = None
    contra_ledger: Optional[str] = None
    approval_notes: Optional[str] = None


# Batch Approval Request
class BatchApproveRequest(BaseModel):
    transaction_ids: List[int]
    approver_user: str = Field(default="finance_admin")


# Batch Details
class ImportBatchOut(BaseModel):
    id: int
    batch_id: str
    filename: str
    file_size_bytes: int
    total_rows: int
    parsed_rows: int
    failed_rows: int
    status: str
    error_message: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Tally Ledger
class TallyLedgerOut(BaseModel):
    id: int
    name: str
    parent_group: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# Audit Log Out
class AuditLogOut(BaseModel):
    id: int
    timestamp: datetime
    actor: str
    action: str
    batch_id: Optional[int]
    transaction_id: Optional[int]
    previous_status: Optional[str]
    new_status: Optional[str]
    summary: str
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


# Dashboard Summary Out
class DashboardSummaryOut(BaseModel):
    total_transactions: int
    processed_transactions: int
    clarification_queue_count: int
    approval_queue_count: int
    failed_transactions: int
    skipped_transactions: int
    tally_connection_status: str
    llm_connection_status: str
    recent_batches: List[ImportBatchOut]
    status_distribution: Dict[str, int]

