from datetime import date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from model.models import BankTransaction, VoucherType


class AccountingValidatorService:
    def __init__(self, default_bank_ledger: str = "HDFC Bank"):
        self.default_bank_ledger = default_bank_ledger

    def validate_transaction(
        self,
        tx: BankTransaction,
        target_ledger: Optional[str],
        voucher_type: Optional[str],
        contra_ledger: Optional[str],
        available_ledgers: List[str]
    ) -> Dict[str, Any]:
        """
        Validates accounting consistency and compliance before allowing voucher posting.
        """
        errors = []
        warnings = []
        requires_clarification = False

        # 1. Date validation
        if not tx.transaction_date:
            errors.append("Transaction date is missing.")
        elif tx.transaction_date > date.today():
            warnings.append(f"Transaction date {tx.transaction_date} is in the future.")

        # 2. Positive monetary amounts
        debit = Decimal(str(tx.debit_amount or 0))
        credit = Decimal(str(tx.credit_amount or 0))

        if debit < 0 or credit < 0:
            errors.append("Transaction amounts cannot be negative.")

        if debit == 0 and credit == 0:
            errors.append("Transaction must have either a non-zero debit or credit amount.")

        if debit > 0 and credit > 0:
            errors.append("Both debit and credit amounts cannot be simultaneously non-zero in a single bank statement line.")

        amount = debit if debit > 0 else credit

        # 3. Target Ledger Verification
        if not target_ledger or target_ledger.strip() == "":
            errors.append("Target ledger is not assigned.")
            requires_clarification = True
        elif target_ledger not in available_ledgers:
            errors.append(f"Target ledger '{target_ledger}' does not exist in Tally master ledgers.")
            requires_clarification = True

        # 4. Bank / Contra Ledger Verification
        effective_contra = contra_ledger or self.default_bank_ledger
        if not effective_contra:
            errors.append("Bank / Contra ledger is not assigned.")
        elif available_ledgers and effective_contra not in available_ledgers:
            bank_candidates = [l for l in available_ledgers if "bank" in l.lower()]
            if bank_candidates:
                effective_contra = bank_candidates[0]
            else:
                errors.append(f"Contra ledger '{effective_contra}' not found in Tally master ledgers.")

        # 5. Voucher Type and Direction Consistency
        if not voucher_type:
            errors.append("Voucher type is unspecified.")
            requires_clarification = True
        else:
            v_type = voucher_type.capitalize()
            if v_type not in [VoucherType.PAYMENT.value, VoucherType.RECEIPT.value, VoucherType.CONTRA.value, VoucherType.JOURNAL.value]:
                errors.append(f"Invalid voucher type '{voucher_type}'.")

            # Check directional coherence
            if debit > 0:
                if v_type == VoucherType.RECEIPT.value:
                    errors.append("Bank debit (money outflow) cannot be recorded as a Receipt voucher.")
                    requires_clarification = True
            elif credit > 0:
                if v_type == VoucherType.PAYMENT.value:
                    errors.append("Bank credit (money inflow) cannot be recorded as a Payment voucher.")
                    requires_clarification = True

        # 6. Double-entry balancing check
        if target_ledger and effective_contra and target_ledger.lower() == effective_contra.lower():
            errors.append("Primary ledger and contra ledger cannot be identical.")
            requires_clarification = True

        is_valid = len(errors) == 0

        return {
            "is_valid": is_valid,
            "requires_clarification": requires_clarification or not is_valid,
            "errors": errors,
            "warnings": warnings,
            "balanced_entry": {
                "amount": float(amount),
                "primary_ledger": target_ledger,
                "contra_ledger": effective_contra,
                "voucher_type": voucher_type
            }
        }

