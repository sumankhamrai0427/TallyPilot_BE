"""Database repositories for TallyPilot v2.0 Clean Architecture.

All repository methods respect multi-tenancy (company_id) and utilize
the normalized double-entry accounting schema.
"""
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_, desc
from decimal import Decimal

from model.models import (
    Company,
    FinancialYear,
    AccountGroup,
    LedgerAccount,
    Party,
    Document,
    BankTransaction,
    TransactionClassification,
    HumanReview,
    ApprovalRecord,
    TransactionStatus,
    ImportBatch,
    TallyLedger,
    TallySubmission,
    AuditLog,
    ApplicationSetting,
    Voucher,
    VoucherLine,
    VoucherApproval,
    GeneralLedger,
    BankReconciliation,
    BankReconciliationItem,
    VoucherStatus,
    VoucherType
)


class CompanyRepository:
    """Multi-tenant company and financial year operations."""

    def __init__(self, db: Session):
        self.db = db

    def list_all(self, is_active: bool = True) -> List[Company]:
        query = self.db.query(Company)
        if is_active:
            query = query.filter(Company.is_active == True)
        return query.order_by(Company.name.asc()).all()

    def get_by_id(self, company_id: int) -> Optional[Company]:
        return self.db.query(Company).filter(Company.id == company_id).first()

    def get_default(self) -> Optional[Company]:
        return self.db.query(Company).filter(Company.is_active == True).order_by(Company.id.asc()).first()

    def get_current_fy(self, company_id: int) -> Optional[FinancialYear]:
        fy = (
            self.db.query(FinancialYear)
            .filter(FinancialYear.company_id == company_id, FinancialYear.is_current == 1)
            .first()
        )
        if not fy:
            fy = (
                self.db.query(FinancialYear)
                .filter(FinancialYear.company_id == company_id)
                .order_by(FinancialYear.id.desc())
                .first()
            )
        if not fy:
            import datetime
            now = datetime.datetime.utcnow()
            fy_start_year = now.year if now.month >= 4 else now.year - 1
            fy = FinancialYear(
                company_id=company_id,
                name=f"FY {fy_start_year}-{str(fy_start_year + 1)[-2:]}",
                start_date=datetime.date(fy_start_year, 4, 1),
                end_date=datetime.date(fy_start_year + 1, 3, 31),
                is_current=1
            )
            self.db.add(fy)
            self.db.commit()
            self.db.refresh(fy)
        return fy

    def list_financial_years(self, company_id: int) -> List[FinancialYear]:
        return (
            self.db.query(FinancialYear)
            .filter(FinancialYear.company_id == company_id)
            .order_by(FinancialYear.start_date.desc())
            .all()
        )

    def get_financial_year(self, fy_id: int) -> Optional[FinancialYear]:
        return self.db.query(FinancialYear).filter(FinancialYear.id == fy_id).first()

    def create_company(self, data: dict) -> Company:
        company = Company(
            name=data["name"],
            code=data.get("code") or f"COMP-{data['name'][:3].upper()}",
            pan=data.get("pan"),
            gstin=data.get("gstin"),
            financial_year_start_month=int(data.get("financial_year_start_month", 4)),
            currency=data.get("currency", "INR"),
            tally_company_name=data.get("tally_company_name") or data["name"],
            tally_url=data.get("tally_url", "http://localhost:9000"),
            default_bank_ledger=data.get("default_bank_ledger") or None,
            tally_simulation_mode=bool(data.get("tally_simulation_mode", True)),
            is_active=bool(data.get("is_active", True))
        )
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        try:
            self.get_current_fy(company.id)
            self.seed_company_chart_of_accounts(company.id)
        except Exception as seed_err:
            print(f">> [CompanyRepository] Notice: could not seed default chart of accounts: {seed_err}")
        return company

    def seed_company_chart_of_accounts(self, company_id: int):
        """Seeds standard accounting groups and initial bank/cash ledgers for a company."""
        standard_groups = [
            ("Bank Accounts", "GRP-BNK", "ASSET", "DEBIT"),
            ("Cash-in-hand", "GRP-CSH", "ASSET", "DEBIT"),
            ("Current Assets", "GRP-CAS", "ASSET", "DEBIT"),
            ("Current Liabilities", "GRP-CLI", "LIABILITY", "CREDIT"),
            ("Sundry Debtors", "GRP-SDR", "ASSET", "DEBIT"),
            ("Sundry Creditors", "GRP-SCR", "LIABILITY", "CREDIT"),
            ("Direct Expenses", "GRP-DIR", "EXPENSE", "DEBIT"),
            ("Indirect Expenses", "GRP-IND", "EXPENSE", "DEBIT"),
            ("Sales Accounts", "GRP-SAL", "INCOME", "CREDIT"),
            ("Purchase Accounts", "GRP-PUR", "EXPENSE", "DEBIT"),
            ("Indirect Incomes", "GRP-INC", "INCOME", "CREDIT"),
            ("Duties & Taxes", "GRP-TAX", "LIABILITY", "CREDIT"),
            ("Capital Account", "GRP-CAP", "EQUITY", "CREDIT"),
        ]

        group_map = {}
        for g_name, g_code, g_type, g_nature in standard_groups:
            grp = self.db.query(AccountGroup).filter(
                AccountGroup.company_id == company_id,
                AccountGroup.name == g_name
            ).first()
            if not grp:
                grp = AccountGroup(
                    company_id=company_id,
                    name=g_name,
                    code=g_code,
                    group_type=g_type,
                    nature=g_nature,
                    affects_gross_profit=(g_type in ["INCOME", "EXPENSE"] and "Direct" in g_name),
                    is_builtin=True
                )
                self.db.add(grp)
                self.db.flush()
            group_map[g_name] = grp

        # Default bank ledger from company setup if provided
        comp = self.get_by_id(company_id)
        bank_name = (comp.default_bank_ledger.strip() if comp and comp.default_bank_ledger else None)
        if bank_name and "Bank Accounts" in group_map:
            bank_ledger = self.db.query(LedgerAccount).filter(
                LedgerAccount.company_id == company_id,
                LedgerAccount.name == bank_name
            ).first()
            if not bank_ledger:
                bank_ledger = LedgerAccount(
                    company_id=company_id,
                    group_id=group_map["Bank Accounts"].id,
                    name=bank_name,
                    code="BNK-001",
                    opening_balance=Decimal("0.00"),
                    current_balance=Decimal("0.00"),
                    is_active=True
                )
                self.db.add(bank_ledger)

        # Cash ledger
        cash_ledger = self.db.query(LedgerAccount).filter(
            LedgerAccount.company_id == company_id,
            LedgerAccount.name == "Cash"
        ).first()
        if not cash_ledger and "Cash-in-hand" in group_map:
            cash_ledger = LedgerAccount(
                company_id=company_id,
                group_id=group_map["Cash-in-hand"].id,
                name="Cash",
                code="CSH-001",
                opening_balance=Decimal("0.00"),
                current_balance=Decimal("0.00"),
                is_active=True
            )
            self.db.add(cash_ledger)

        # Standard operational ledgers required for standard business double-entry accounting
        standard_ledgers = [
            ("Salary Expenses", "Indirect Expenses", "EXP-SAL"),
            ("Bank Charges", "Indirect Expenses", "EXP-BNK"),
            ("Electricity Expenses", "Indirect Expenses", "EXP-ELE"),
            ("Office Rent", "Indirect Expenses", "EXP-RNT"),
            ("Telephone & Internet Charges", "Indirect Expenses", "EXP-TEL"),
            ("Travelling & Conveyance", "Indirect Expenses", "EXP-TRV"),
            ("Software & Subscription Expenses", "Indirect Expenses", "EXP-SFT"),
            ("Printing & Stationery", "Indirect Expenses", "EXP-STN"),
            ("GST Tax Liability", "Duties & Taxes", "TAX-GST"),
            ("Counter Sales", "Sales Accounts", "SAL-CTR"),
            ("Advance from Customers", "Current Liabilities", "LIA-ADV"),
            ("Prepaid Insurance", "Current Assets", "AST-INS"),
            ("Prepaid IT Support AMC", "Current Assets", "AST-AMC"),
            ("Suspense Account", "Indirect Expenses", "EXP-SUS"),
        ]

        for l_name, target_group, l_code in standard_ledgers:
            if target_group in group_map:
                existing_ledger = self.db.query(LedgerAccount).filter(
                    LedgerAccount.company_id == company_id,
                    LedgerAccount.name == l_name
                ).first()
                if not existing_ledger:
                    new_led = LedgerAccount(
                        company_id=company_id,
                        group_id=group_map[target_group].id,
                        name=l_name,
                        code=l_code,
                        opening_balance=Decimal("0.00"),
                        current_balance=Decimal("0.00"),
                        is_active=True
                    )
                    self.db.add(new_led)
                elif existing_ledger.group_id != group_map[target_group].id:
                    # Self-heal ledger group (e.g. if GST Tax Liability was under Sundry Creditors)
                    existing_ledger.group_id = group_map[target_group].id

        self.db.commit()

    def update_company(self, company_id: int, data: dict) -> Optional[Company]:
        comp = self.get_by_id(company_id)
        if not comp:
            return None
        if "name" in data:
            comp.name = data["name"]
        if "code" in data:
            comp.code = data["code"]
        if "pan" in data:
            comp.pan = data["pan"]
        if "gstin" in data:
            comp.gstin = data["gstin"]
        if "currency" in data:
            comp.currency = data["currency"]
        if "financial_year_start_month" in data:
            comp.financial_year_start_month = int(data["financial_year_start_month"])
        if "tally_company_name" in data:
            comp.tally_company_name = data["tally_company_name"]
        if "tally_url" in data:
            comp.tally_url = data["tally_url"]
        if "default_bank_ledger" in data:
            comp.default_bank_ledger = data["default_bank_ledger"]
        if "tally_simulation_mode" in data:
            comp.tally_simulation_mode = bool(data["tally_simulation_mode"])
        if "is_active" in data:
            comp.is_active = bool(data["is_active"])
        self.db.commit()
        self.db.refresh(comp)
        return comp

    def create_financial_year(self, company_id: int, data: dict) -> FinancialYear:
        from datetime import date
        start_date = data["start_date"]
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        end_date = data["end_date"]
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        is_current_requested = bool(data.get("is_current", False))
        if is_current_requested:
            # Unset existing current FY for this company to NULL
            # (MySQL chk_fy_current requires is_current IS NULL OR is_current = 1)
            self.db.query(FinancialYear).filter(
                FinancialYear.company_id == company_id
            ).update({"is_current": None})
            db_is_current = 1
        else:
            db_is_current = None

        fy = FinancialYear(
            company_id=company_id,
            fy_code=data["fy_code"],
            start_date=start_date,
            end_date=end_date,
            is_current=db_is_current,
            is_closed=bool(data.get("is_closed", False))
        )
        self.db.add(fy)
        self.db.commit()
        self.db.refresh(fy)
        return fy

    def set_current_financial_year(self, company_id: int, fy_id: int) -> Optional[FinancialYear]:
        fy = self.get_financial_year(fy_id)
        if not fy or fy.company_id != company_id:
            return None
        # MySQL uq_fy_comp_current & chk_fy_current require NULL for non-current years
        self.db.query(FinancialYear).filter(
            FinancialYear.company_id == company_id
        ).update({"is_current": None})
        fy.is_current = 1
        self.db.commit()
        self.db.refresh(fy)
        return fy

    def toggle_financial_year_lock(self, fy_id: int, is_closed: Optional[bool] = None) -> Optional[FinancialYear]:
        fy = self.get_financial_year(fy_id)
        if not fy:
            return None
        if is_closed is not None:
            fy.is_closed = is_closed
        else:
            fy.is_closed = not bool(fy.is_closed)
        self.db.commit()
        self.db.refresh(fy)
        return fy


class LedgerRepository:
    """Chart of accounts, ledgers, and party master management."""

    def __init__(self, db: Session):
        self.db = db

    def list_groups(self, company_id: int) -> List[AccountGroup]:
        return (
            self.db.query(AccountGroup)
            .filter(AccountGroup.company_id == company_id)
            .order_by(AccountGroup.parent_id.asc(), AccountGroup.name.asc())
            .all()
        )

    def list_by_company(self, company_id: int, is_active: Optional[bool] = True) -> List[LedgerAccount]:
        query = self.db.query(LedgerAccount).options(joinedload(LedgerAccount.group)).filter(
            LedgerAccount.company_id == company_id
        )
        if is_active is not None:
            query = query.filter(LedgerAccount.is_active == is_active)
        return query.order_by(LedgerAccount.name.asc()).all()

    def list_bank_ledgers(self, company_id: int, is_active: Optional[bool] = True) -> List[LedgerAccount]:
        """Lists all active bank account ledgers under Bank Accounts / OD groups for the company."""
        query = (
            self.db.query(LedgerAccount)
            .join(AccountGroup, AccountGroup.id == LedgerAccount.group_id)
            .options(joinedload(LedgerAccount.group))
            .filter(
                LedgerAccount.company_id == company_id,
                AccountGroup.name.in_(("Bank Accounts", "Bank OD A/c", "Bank OCC A/c"))
            )
        )
        if is_active is not None:
            query = query.filter(LedgerAccount.is_active == is_active)
        return query.order_by(LedgerAccount.name.asc()).all()

    def get_by_id(self, ledger_id: int, company_id: int) -> Optional[LedgerAccount]:
        return (
            self.db.query(LedgerAccount)
            .options(joinedload(LedgerAccount.group))
            .filter(LedgerAccount.id == ledger_id, LedgerAccount.company_id == company_id)
            .first()
        )

    def get_by_name(self, name: str, company_id: int) -> Optional[LedgerAccount]:
        return (
            self.db.query(LedgerAccount)
            .filter(LedgerAccount.company_id == company_id, LedgerAccount.name == name)
            .first()
        )

    def list_parties(self, company_id: int, party_type: Optional[str] = None) -> List[Party]:
        query = self.db.query(Party).options(joinedload(Party.ledger)).filter(
            Party.company_id == company_id,
            Party.is_active == True
        )
        if party_type:
            query = query.filter(Party.party_type == party_type)
        return query.all()

    def get_chart_of_accounts_tree(self, company_id: int) -> List[Dict[str, Any]]:
        """Constructs a hierarchical Chart of Accounts tree for the company."""
        groups = self.list_groups(company_id)
        ledgers = self.list_by_company(company_id, is_active=True)

        group_map = {}
        for g in groups:
            group_map[g.id] = {
                "id": g.id,
                "name": g.name,
                "code": g.code,
                "group_type": g.group_type,
                "nature": g.nature,
                "parent_id": g.parent_id,
                "children": [],
                "ledgers": []
            }

        for l in ledgers:
            ledger_dict = {
                "id": l.id,
                "name": l.name,
                "code": l.code,
                "group_id": l.group_id,
                "opening_balance": float(l.opening_balance),
                "current_balance": float(l.current_balance),
                "is_active": l.is_active
            }
            if l.group_id in group_map:
                group_map[l.group_id]["ledgers"].append(ledger_dict)

        root_groups = []
        for g_id, g_data in group_map.items():
            if g_data["parent_id"] and g_data["parent_id"] in group_map:
                group_map[g_data["parent_id"]]["children"].append(g_data)
            else:
                root_groups.append(g_data)

        return root_groups

    # Backward compatibility with tally sync
    def list_all(self, active_only: bool = True) -> List[TallyLedger]:
        query = self.db.query(TallyLedger)
        if active_only:
            query = query.filter(TallyLedger.is_active == True)
        return query.order_by(TallyLedger.name.asc()).all()

    def upsert(self, name: str, parent_group: str, guid: Optional[str] = None) -> TallyLedger:
        ledger = self.db.query(TallyLedger).filter(TallyLedger.name == name).first()
        if ledger:
            ledger.parent_group = parent_group
            if guid:
                ledger.guid = guid
            ledger.is_active = True
        else:
            ledger = TallyLedger(name=name, parent_group=parent_group, guid=guid, is_active=True)
            self.db.add(ledger)
        self.db.commit()
        self.db.refresh(ledger)
        return ledger


class VoucherRepository:
    """Double-entry voucher querying and reporting."""

    def __init__(self, db: Session):
        self.db = db

    def list_vouchers(
        self,
        company_id: int,
        fy_id: Optional[int] = None,
        voucher_type: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[Voucher], int]:
        query = (
            self.db.query(Voucher)
            .options(
                joinedload(Voucher.lines).joinedload(VoucherLine.ledger),
                joinedload(Voucher.lines).joinedload(VoucherLine.party),
                joinedload(Voucher.bank_transaction)
            )
            .filter(Voucher.company_id == company_id)
        )

        if fy_id:
            query = query.filter(Voucher.fy_id == fy_id)
        if voucher_type:
            query = query.filter(Voucher.voucher_type == voucher_type)
        if status:
            query = query.filter(Voucher.status == status)
        if search:
            search_fmt = f"%{search}%"
            query = query.filter(
                or_(
                    Voucher.voucher_number.ilike(search_fmt),
                    Voucher.narration.ilike(search_fmt)
                )
            )

        total = query.count()
        results = query.order_by(Voucher.voucher_date.desc(), Voucher.id.desc()).offset(skip).limit(limit).all()
        return results, total

    def get_voucher_by_id(self, voucher_id: int, company_id: int) -> Optional[Voucher]:
        return (
            self.db.query(Voucher)
            .options(
                joinedload(Voucher.lines).joinedload(VoucherLine.ledger),
                joinedload(Voucher.lines).joinedload(VoucherLine.party),
                joinedload(Voucher.bank_transaction),
                joinedload(Voucher.approvals)
            )
            .filter(Voucher.id == voucher_id, Voucher.company_id == company_id)
            .first()
        )

    def get_gl_entries(
        self,
        company_id: int,
        ledger_id: Optional[int] = None,
        voucher_id: Optional[int] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[GeneralLedger], int]:
        query = (
            self.db.query(GeneralLedger)
            .options(
                joinedload(GeneralLedger.ledger),
                joinedload(GeneralLedger.voucher)
            )
            .filter(GeneralLedger.company_id == company_id)
        )

        if ledger_id:
            query = query.filter(GeneralLedger.ledger_id == ledger_id)
        if voucher_id:
            query = query.filter(GeneralLedger.voucher_id == voucher_id)
        if from_date:
            query = query.filter(GeneralLedger.posting_date >= from_date)
        if to_date:
            query = query.filter(GeneralLedger.posting_date <= to_date)

        total = query.count()
        entries = query.order_by(GeneralLedger.posting_date.desc(), GeneralLedger.id.desc()).offset(skip).limit(limit).all()
        return entries, total

    def get_ledger_balances(self, company_id: int, fy_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Calculates running debit, credit, and net balance for each ledger in the company."""
        query = (
            self.db.query(
                GeneralLedger.ledger_id,
                LedgerAccount.name.label("ledger_name"),
                func.sum(GeneralLedger.debit_amount).label("total_debit"),
                func.sum(GeneralLedger.credit_amount).label("total_credit")
            )
            .join(LedgerAccount, LedgerAccount.id == GeneralLedger.ledger_id)
            .filter(GeneralLedger.company_id == company_id)
        )

        if fy_id:
            query = query.filter(GeneralLedger.fy_id == fy_id)

        rows = query.group_by(GeneralLedger.ledger_id, LedgerAccount.name).all()

        balances = []
        for r in rows:
            dr = Decimal(str(r.total_debit or 0))
            cr = Decimal(str(r.total_credit or 0))
            net = dr - cr
            balances.append({
                "ledger_id": r.ledger_id,
                "ledger_name": r.ledger_name,
                "total_debit": float(dr),
                "total_credit": float(cr),
                "net_balance": float(net),
                "balance_nature": "DR" if net >= 0 else "CR"
            })
        return balances


class TransactionRepository:
    """Bank transactions data access with multi-tenant company_id support."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, tx_id: int, company_id: Optional[int] = None) -> Optional[BankTransaction]:
        query = self.db.query(BankTransaction).filter(BankTransaction.id == tx_id)
        if company_id is not None:
            query = query.filter(BankTransaction.company_id == company_id)
        return query.first()

    def list_filtered(
        self,
        company_id: Optional[int] = None,
        batch_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        requires_review: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[BankTransaction], int]:
        query = self.db.query(BankTransaction)

        if company_id is not None:
            query = query.filter(BankTransaction.company_id == company_id)
        if batch_id is not None:
            query = query.filter(BankTransaction.batch_id == batch_id)
        if status:
            query = query.filter(BankTransaction.status == status)
        if requires_review is not None:
            query = query.filter(BankTransaction.requires_review == requires_review)
        if search:
            search_fmt = f"%{search}%"
            query = query.filter(
                or_(
                    BankTransaction.narration.ilike(search_fmt),
                    BankTransaction.bank_reference.ilike(search_fmt)
                )
            )

        total = query.count()
        results = query.order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc()).offset(skip).limit(limit).all()
        return results, total

    def count_by_status(self, company_id: Optional[int] = None) -> Dict[str, int]:
        query = self.db.query(BankTransaction.status, func.count(BankTransaction.id))
        if company_id is not None:
            query = query.filter(BankTransaction.company_id == company_id)
        rows = query.group_by(BankTransaction.status).all()
        return {status: count for status, count in rows}

    def total_count(self, company_id: Optional[int] = None) -> int:
        query = self.db.query(func.count(BankTransaction.id))
        if company_id is not None:
            query = query.filter(BankTransaction.company_id == company_id)
        return query.scalar() or 0

    def create(self, tx: BankTransaction) -> BankTransaction:
        self.db.add(tx)
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def update(self, tx: BankTransaction) -> BankTransaction:
        self.db.commit()
        self.db.refresh(tx)
        return tx

    def add_classification(self, classification: TransactionClassification) -> TransactionClassification:
        self.db.add(classification)
        self.db.commit()
        self.db.refresh(classification)
        return classification

    def add_review(self, review: HumanReview) -> HumanReview:
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def add_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval


class BatchRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, batch: ImportBatch) -> ImportBatch:
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def update(self, batch: ImportBatch) -> ImportBatch:
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def get_by_id(self, batch_id: int) -> Optional[ImportBatch]:
        return self.db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()

    def get_by_batch_id_str(self, batch_id_str: str) -> Optional[ImportBatch]:
        return self.db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id_str).first()

    def get_by_file_hash(self, file_hash: str, company_id: Optional[int] = None) -> Optional[ImportBatch]:
        query = self.db.query(ImportBatch).filter(ImportBatch.file_hash == file_hash)
        if company_id is not None:
            query = query.filter(ImportBatch.company_id == company_id)
        return query.first()

    def list_recent(self, company_id: Optional[int] = None, limit: int = 20) -> List[ImportBatch]:
        query = self.db.query(ImportBatch)
        if company_id is not None:
            query = query.filter(ImportBatch.company_id == company_id)
        return query.order_by(ImportBatch.created_at.desc()).limit(limit).all()


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        document: Optional[Document] = None,
        company_id: Optional[int] = None,
        filename: Optional[str] = None,
        file_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        file_size_bytes: int = 0,
        document_type: str = "BANK_STATEMENT",
        mime_type: Optional[str] = None,
        uploaded_by: str = "SYSTEM",
        status: str = "PENDING",
        **kwargs
    ) -> Document:
        """Create a new document record.
        
        Supports passing either a Document entity instance (standard repository pattern):
            repo.create(doc)
        Or passing keyword arguments directly:
            repo.create(company_id=1, filename="...", ...)
        """
        if isinstance(document, Document):
            doc = document
        else:
            cid = company_id or kwargs.get("company_id")
            fn = filename or kwargs.get("filename")
            fp = file_path or kwargs.get("file_path")
            fh = file_hash or kwargs.get("file_hash")
            fs = file_size_bytes if file_size_bytes != 0 else kwargs.get("file_size_bytes", 0)
            dt = document_type or kwargs.get("document_type", "BANK_STATEMENT")
            mt = mime_type or kwargs.get("mime_type")
            ub = uploaded_by or kwargs.get("uploaded_by", "SYSTEM")
            st = status or kwargs.get("status", "PENDING")
            
            doc = Document(
                company_id=cid,
                document_type=dt,
                filename=fn,
                file_path=fp,
                file_hash=fh,
                file_size_bytes=fs,
                mime_type=mt,
                uploaded_by=ub,
                status=st
            )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        return doc

    def get_by_hash(self, file_hash: str, company_id: Optional[int] = None) -> Optional[Document]:
        query = self.db.query(Document).filter(Document.file_hash == file_hash)
        if company_id is not None:
            query = query.filter(Document.company_id == company_id)
        return query.first()

    def list_by_company(self, company_id: int, limit: int = 50, document_type: Optional[str] = None) -> List[Document]:
        query = self.db.query(Document).filter(Document.company_id == company_id)
        if document_type:
            query = query.filter(Document.document_type == document_type)
        return query.order_by(Document.created_at.desc()).limit(limit).all()

    def get_by_id(self, doc_id: int, company_id: Optional[int] = None) -> Optional[Document]:
        query = self.db.query(Document).filter(Document.id == doc_id)
        if company_id is not None:
            query = query.filter(Document.company_id == company_id)
        return query.first()


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: str,
        summary: str,
        actor: str = "SYSTEM",
        company_id: Optional[int] = None,
        batch_id: Optional[int] = None,
        transaction_id: Optional[int] = None,
        previous_status: Optional[str] = None,
        new_status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        if company_id is None:
            comp = self.db.query(Company).filter(Company.is_active == True).first()
            company_id = comp.id if comp else 1

        entry = AuditLog(
            action=action,
            summary=summary,
            actor=actor,
            company_id=company_id,
            batch_id=batch_id,
            transaction_id=transaction_id,
            previous_status=previous_status,
            new_status=new_status,
            details=details
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def list_filtered(
        self,
        company_id: Optional[int] = None,
        action: Optional[str] = None,
        transaction_id: Optional[int] = None,
        batch_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[AuditLog], int]:
        query = self.db.query(AuditLog)
        if company_id is not None:
            query = query.filter(AuditLog.company_id == company_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if transaction_id:
            query = query.filter(AuditLog.transaction_id == transaction_id)
        if batch_id:
            query = query.filter(AuditLog.batch_id == batch_id)
        total = query.count()
        results = query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
        return results, total


class SettingsRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self, company_id: Optional[int] = None) -> Dict[str, str]:
        query = self.db.query(ApplicationSetting)
        rows = query.all()
        return {r.key: r.value for r in rows}

    def get(self, key: str, default: Optional[str] = None, company_id: Optional[int] = None) -> Optional[str]:
        query = self.db.query(ApplicationSetting).filter(ApplicationSetting.key == key)
        setting = query.first()
        return setting.value if setting else default

    def set(self, key: str, value: str, description: Optional[str] = None, company_id: Optional[int] = None) -> ApplicationSetting:
        query = self.db.query(ApplicationSetting).filter(ApplicationSetting.key == key)
        setting = query.first()
        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            setting = ApplicationSetting(key=key, value=value, description=description)
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting
