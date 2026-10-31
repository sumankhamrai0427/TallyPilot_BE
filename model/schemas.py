from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from model.models import (
    TransactionStatus, VoucherType, VoucherStatus, 
    AccountGroupType, AccountNature, PartyType
)


# ============================================================================
# COMPANY & FINANCIAL PERIOD SCHEMAS
# ============================================================================
class CompanyOut(BaseModel):
    id: int
    name: str
    code: str
    pan: Optional[str] = None
    gstin: Optional[str] = None
    financial_year_start_month: int
    currency: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FinancialYearOut(BaseModel):
    id: int
    company_id: int
    fy_code: str
    start_date: date
    end_date: date
    is_current: Optional[bool]
    is_closed: bool

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# CHART OF ACCOUNTS & PARTIES SCHEMAS
# ============================================================================
class AccountGroupOut(BaseModel):
    id: int
    company_id: int
    name: str
    code: Optional[str] = None
    parent_id: Optional[int] = None
    group_type: str
    nature: str
    affects_gross_profit: bool
    is_builtin: bool

    model_config = ConfigDict(from_attributes=True)


class LedgerAccountOut(BaseModel):
    id: int
    company_id: int
    group_id: int
    name: str
    code: Optional[str] = None
    opening_balance: Decimal
    current_balance: Decimal
    is_subledger: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PartyOut(BaseModel):
    id: int
    company_id: int
    ledger_id: int
    party_type: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    credit_limit: Decimal
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ChartOfAccountsTree(BaseModel):
    groups: List[AccountGroupOut]
    ledgers: List[LedgerAccountOut]


# ============================================================================
# AI & TRANSACTIONS SCHEMAS
# ============================================================================
class AICorrectionProposal(BaseModel):
    transaction_type: str = Field(..., description="E.g., supplier_payment, customer_receipt, bank_charges, cash_withdrawal")
    suggested_voucher_type: VoucherType = Field(..., description="Payment, Receipt, Contra, or Journal")
    suggested_ledger: Optional[str] = Field(None, description="Exact matching ledger from supplied Tally ledgers")
    contra_ledger: Optional[str] = Field(None, description="Bank or cash ledger name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence estimate between 0.0 and 1.0")
    requires_human_review: bool = Field(True, description="True if uncertain or requires verification")
    ambiguity_reason: Optional[str] = Field(None, description="Explanation why clarification is required")
    explanation: Optional[str] = Field(None, description="Concise rationale for suggestion")


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
    company_id: int
    transaction_id: int
    model_name: str
    transaction_type: str
    suggested_voucher_type: str
    suggested_ledger: Optional[str]
    suggested_ledger_id: Optional[int] = None
    contra_ledger: Optional[str]
    contra_ledger_id: Optional[int] = None
    confidence: float
    explanation: Optional[str]
    ambiguity_reason: Optional[str]
    requires_human_review: bool
    is_fallback_rule: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HumanReviewOut(BaseModel):
    id: int
    company_id: int
    reviewer_user: str
    corrected_transaction_type: str
    corrected_voucher_type: str
    selected_ledger: str
    selected_ledger_id: Optional[int] = None
    contra_ledger: Optional[str]
    contra_ledger_id: Optional[int] = None
    reviewer_notes: Optional[str]
    resolution_action: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankTransactionOut(BaseModel):
    id: int
    company_id: int
    batch_id: int
    bank_ledger_id: int
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
    reconciliation_status: str
    created_at: datetime
    classification: Optional[TransactionClassificationOut] = None
    reviews: List[HumanReviewOut] = []

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# DOUBLE-ENTRY VOUCHER SCHEMAS
# ============================================================================
class VoucherLineCreate(BaseModel):
    line_number: int
    ledger_id: int
    party_id: Optional[int] = None
    debit_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    credit_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    narration: Optional[str] = None


class VoucherLineOut(BaseModel):
    id: int
    company_id: int
    voucher_id: int
    line_number: int
    ledger_id: int
    party_id: Optional[int] = None
    debit_amount: Decimal
    credit_amount: Decimal
    narration: Optional[str] = None
    ledger_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VoucherCreate(BaseModel):
    voucher_number: Optional[str] = None
    voucher_type: VoucherType
    voucher_date: date
    narration: Optional[str] = None
    bank_transaction_id: Optional[int] = None
    source_document_id: Optional[int] = None
    lines: List[VoucherLineCreate]


class VoucherOut(BaseModel):
    id: int
    company_id: int
    fy_id: int
    voucher_number: str
    voucher_type: str
    voucher_date: date
    total_amount: Decimal
    narration: Optional[str]
    bank_transaction_id: Optional[int]
    status: str
    created_by: str
    posted_at: Optional[datetime]
    created_at: datetime
    lines: List[VoucherLineOut] = []

    model_config = ConfigDict(from_attributes=True)


class GeneralLedgerOut(BaseModel):
    id: int
    company_id: int
    fy_id: int
    voucher_id: int
    voucher_line_id: int
    posting_date: date
    ledger_id: int
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    is_reversed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# ACTIONS & WORKFLOW REQUESTS
# ============================================================================
class ClarifyTransactionRequest(BaseModel):
    selected_ledger: str = Field(..., min_length=1, description="Chosen Tally ledger name")
    corrected_voucher_type: VoucherType = Field(..., description="Voucher type (Payment, Receipt, Contra, Journal)")
    corrected_transaction_type: str = Field(..., min_length=1, description="Category classification")
    reviewer_notes: Optional[str] = Field(None, description="Optional notes from accountant")
    resolution_action: str = Field(default="SUBMIT_CORRECTION")


class SkipTransactionRequest(BaseModel):
    reason: str = Field(..., min_length=2, description="Reason for skipping this transaction")


class ApproveTransactionRequest(BaseModel):
    approver_user: str = Field(default="finance_admin")
    voucher_type: Optional[VoucherType] = None
    primary_ledger: Optional[str] = None
    contra_ledger: Optional[str] = None
    approval_notes: Optional[str] = None


class BatchApproveRequest(BaseModel):
    transaction_ids: List[int]
    approver_user: str = Field(default="finance_admin")


class ImportBatchOut(BaseModel):
    id: int
    company_id: int
    batch_id: str
    filename: str
    file_size_bytes: int
    total_rows: int
    parsed_rows: int
    failed_rows: int
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TallyLedgerOut(BaseModel):
    id: int
    company_id: int
    name: str
    parent_group: str
    internal_ledger_id: Optional[int] = None
    sync_status: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class AuditLogOut(BaseModel):
    id: int
    company_id: int
    timestamp: datetime
    actor: str
    action: str
    batch_id: Optional[int] = None
    transaction_id: Optional[int] = None
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    summary: str
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class DashboardSummaryOut(BaseModel):
    total_transactions: int = 0
    processed_transactions: int = 0
    clarification_queue_count: int = 0
    approval_queue_count: int = 0
    failed_transactions: int = 0
    skipped_transactions: int = 0
    bank_balance: Decimal = Decimal("0.00")
    cash_balance: Decimal = Decimal("0.00")
    total_receivables: Decimal = Decimal("0.00")
    total_payables: Decimal = Decimal("0.00")
    tally_connection_status: str = "offline"
    llm_connection_status: str = "fallback_active"
    recent_batches: List[ImportBatchOut] = []
    status_distribution: Dict[str, int] = {}
