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
        return (
            self.db.query(FinancialYear)
            .filter(FinancialYear.company_id == company_id, FinancialYear.is_current == 1)
            .first()
        )

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
            default_bank_ledger=data.get("default_bank_ledger", "HDFC Bank"),
            tally_simulation_mode=bool(data.get("tally_simulation_mode", True)),
            is_active=bool(data.get("is_active", True))
        )
        self.db.add(company)
        self.db.commit()
        self.db.refresh(company)
        return company

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

        is_current = bool(data.get("is_current", False))
        if is_current:
            # Unset existing current FY for this company
            self.db.query(FinancialYear).filter(
                FinancialYear.company_id == company_id
            ).update({"is_current": False})

        fy = FinancialYear(
            company_id=company_id,
            fy_code=data["fy_code"],
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
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
        self.db.query(FinancialYear).filter(
            FinancialYear.company_id == company_id
        ).update({"is_current": False})
        fy.is_current = True
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

    def get_by_id(self, batch_id: int) -> Optional[ImportBatch]:
        return self.db.query(ImportBatch).filter(ImportBatch.id == batch_id).first()

    def get_by_batch_id_str(self, batch_id_str: str) -> Optional[ImportBatch]:
        return self.db.query(ImportBatch).filter(ImportBatch.batch_id == batch_id_str).first()

    def get_by_file_hash(self, file_hash: str) -> Optional[ImportBatch]:
        return self.db.query(ImportBatch).filter(ImportBatch.file_hash == file_hash).first()

    def list_recent(self, company_id: Optional[int] = None, limit: int = 20) -> List[ImportBatch]:
        query = self.db.query(ImportBatch)
        if company_id is not None:
            query = query.filter(ImportBatch.company_id == company_id)
        return query.order_by(ImportBatch.created_at.desc()).limit(limit).all()

    def create(self, batch: ImportBatch) -> ImportBatch:
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def update(self, batch: ImportBatch) -> ImportBatch:
        self.db.commit()
        self.db.refresh(batch)
        return batch


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
