from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from model.models import (
    BankTransaction,
    TransactionClassification,
    HumanReview,
    ApprovalRecord,
    TransactionStatus,
    ImportBatch,
    TallyLedger,
    AuditLog,
    ApplicationSetting
)


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, tx_id: int) -> Optional[BankTransaction]:
        return self.db.query(BankTransaction).filter(BankTransaction.id == tx_id).first()

    def list_filtered(
        self,
        batch_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        requires_review: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[BankTransaction], int]:
        query = self.db.query(BankTransaction)

        if batch_id is not None:
            query = query.filter(BankTransaction.batch_id == batch_id)
        if status:
            query = query.filter(BankTransaction.status == status)
        if requires_review is not None:
            query = query.filter(BankTransaction.requires_review == requires_review)
        if search:
            search_fmt = f"%{search}%"
            query = query.filter(
                (BankTransaction.narration.ilike(search_fmt)) |
                (BankTransaction.bank_reference.ilike(search_fmt))
            )

        total = query.count()
        results = query.order_by(BankTransaction.transaction_date.desc(), BankTransaction.id.desc()).offset(skip).limit(limit).all()
        return results, total

    def count_by_status(self) -> Dict[str, int]:
        rows = self.db.query(BankTransaction.status, func.count(BankTransaction.id)).group_by(BankTransaction.status).all()
        return {status: count for status, count in rows}

    def total_count(self) -> int:
        return self.db.query(func.count(BankTransaction.id)).scalar() or 0

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

    def list_recent(self, limit: int = 20) -> List[ImportBatch]:
        return self.db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit).all()

    def create(self, batch: ImportBatch) -> ImportBatch:
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def update(self, batch: ImportBatch) -> ImportBatch:
        self.db.commit()
        self.db.refresh(batch)
        return batch


class LedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self, active_only: bool = True) -> List[TallyLedger]:
        query = self.db.query(TallyLedger)
        if active_only:
            query = query.filter(TallyLedger.is_active == True)
        return query.order_by(TallyLedger.name.asc()).all()

    def get_by_name(self, name: str) -> Optional[TallyLedger]:
        return self.db.query(TallyLedger).filter(TallyLedger.name == name).first()

    def upsert(self, name: str, parent_group: str, guid: Optional[str] = None) -> TallyLedger:
        ledger = self.get_by_name(name)
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


class AuditRepository:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        action: str,
        summary: str,
        actor: str = "SYSTEM",
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
        action: Optional[str] = None,
        transaction_id: Optional[int] = None,
        batch_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 50
    ) -> Tuple[List[AuditLog], int]:
        query = self.db.query(AuditLog)
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

    def get_all(self) -> Dict[str, str]:
        rows = self.db.query(ApplicationSetting).all()
        return {r.key: r.value for r in rows}

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        setting = self.db.query(ApplicationSetting).filter(ApplicationSetting.key == key).first()
        return setting.value if setting else default

    def set(self, key: str, value: str, description: Optional[str] = None) -> ApplicationSetting:
        setting = self.db.query(ApplicationSetting).filter(ApplicationSetting.key == key).first()
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

