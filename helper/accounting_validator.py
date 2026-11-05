from datetime import date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from model.models import BankTransaction, VoucherType


class AccountingValidatorService:
    """
    Tally Prime Multi-Stage Accounting Validation Architecture.
    Implements 6 distinct validation gates:
      Stage 1: Debit-Credit Arithmetic Balancing
      Stage 2: Ledger Identity & Group Guard (Ledger cannot be a group name; primary != contra)
      Stage 3: Business Context & Directional Integrity (Inflow != Payment, Advance/Prepaid classification)
      Stage 4: Duplicate Transaction & Idempotency Detection
      Stage 5: Human Approval Gate (Refunds, low confidence < 0.80, Suspense Account)
      Stage 6: Final Tally Prime Staging Qualification
    """

    def __init__(self, default_bank_ledger: str = "State Bank Of India"):
        self.default_bank_ledger = default_bank_ledger

    def validate_transaction(
        self,
        tx: BankTransaction,
        target_ledger: Optional[str],
        voucher_type: Optional[str],
        contra_ledger: Optional[str],
        available_ledgers: List[str],
        allow_new_ledger: bool = False,
        suggested_group: Optional[str] = None,
        confidence: float = 1.0,
        is_refund: bool = False,
        is_advance: bool = False,
        existing_tx_references: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        stages = {
            "stage_1_balancing": False,
            "stage_2_ledger_identity": False,
            "stage_3_business_context": False,
            "stage_4_duplicate_detection": False,
            "stage_5_human_approval_gate": False,
            "stage_6_tally_qualification": False,
        }

        stage_details = {}
        errors = []
        warnings = []
        requires_clarification = False

        debit = Decimal(str(tx.debit_amount or 0))
        credit = Decimal(str(tx.credit_amount or 0))
        amount = debit if debit > 0 else credit
        narr_lower = (tx.narration or "").lower()

        # =====================================================================
        # STAGE 1: Debit-Credit Arithmetic Balancing
        # =====================================================================
        if not tx.transaction_date:
            errors.append("Transaction date is missing.")
        elif tx.transaction_date > date.today():
            warnings.append(f"Transaction date {tx.transaction_date} is in the future.")

        if debit < 0 or credit < 0:
            errors.append("Transaction amounts cannot be negative.")

        if debit == 0 and credit == 0:
            errors.append("Transaction must have either a non-zero debit or credit amount.")

        if debit > 0 and credit > 0:
            errors.append("Both debit and credit cannot be simultaneously non-zero in a single bank statement line.")

        if len(errors) == 0:
            stages["stage_1_balancing"] = True
            stage_details["stage_1"] = "Passed: Positive non-zero amount balanced."
        else:
            stage_details["stage_1"] = f"Failed: {', '.join(errors)}"

        # =====================================================================
        # STAGE 2: Ledger Identity & Group Guard
        # =====================================================================
        generic_group_names = {
            "sundry creditors", "sundry debtors", "direct expenses", "indirect expenses",
            "bank accounts", "cash-in-hand", "sales accounts", "purchase accounts",
            "duties & taxes", "capital account", "current assets", "current liabilities",
            "indirect incomes"
        }

        t_ledger = (target_ledger or "").strip()
        effective_contra = (contra_ledger or self.default_bank_ledger).strip()

        if not t_ledger:
            errors.append("Target ledger is not assigned.")
            requires_clarification = True
        elif t_ledger.lower() in generic_group_names:
            errors.append(f"Target ledger '{t_ledger}' is an Account Group name, not an entity/expense ledger.")
            requires_clarification = True
        elif t_ledger not in available_ledgers:
            if allow_new_ledger:
                warnings.append(f"Target ledger '{t_ledger}' will be registered under '{suggested_group or 'Indirect Expenses'}'.")
            else:
                errors.append(f"Target ledger '{t_ledger}' does not exist in master ledgers.")
                requires_clarification = True

        # Check primary != contra on non-Contra vouchers
        v_type = (voucher_type or "").capitalize()
        if t_ledger and effective_contra and t_ledger.lower() == effective_contra.lower() and v_type != VoucherType.CONTRA.value:
            errors.append(f"Primary ledger and bank ledger cannot be identical ('{t_ledger}').")
            requires_clarification = True

        if t_ledger and t_ledger.lower() not in generic_group_names and (t_ledger in available_ledgers or allow_new_ledger):
            stages["stage_2_ledger_identity"] = True
            stage_details["stage_2"] = f"Passed: Valid ledger '{t_ledger}' identified."
        else:
            stage_details["stage_2"] = "Failed: Invalid or unmapped ledger identity."

        # =====================================================================
        # STAGE 3: Business Context & Directional Integrity
        # =====================================================================
        if not voucher_type:
            errors.append("Voucher type is unspecified.")
            requires_clarification = True
        else:
            if v_type not in [VoucherType.PAYMENT.value, VoucherType.RECEIPT.value, VoucherType.CONTRA.value, VoucherType.JOURNAL.value]:
                errors.append(f"Invalid voucher type '{voucher_type}'.")
                requires_clarification = True

            # Directional checks
            if debit > 0 and v_type == VoucherType.RECEIPT.value:
                errors.append("Bank debit (money outflow) cannot be recorded as a Receipt voucher.")
                requires_clarification = True
            elif credit > 0 and v_type == VoucherType.PAYMENT.value:
                errors.append("Bank credit (money inflow) cannot be recorded as a Payment voucher.")
                requires_clarification = True

            # Contra checks
            if v_type == VoucherType.CONTRA.value and t_ledger.lower() not in ["cash"] and "bank" not in t_ledger.lower():
                errors.append(f"Contra voucher requires Cash or Bank account; '{t_ledger}' is invalid for Contra.")
                requires_clarification = True

            # Customer advance tagging
            if is_advance or any(k in narr_lower for k in ["advance for order", "customer advance", "distributors advance"]):
                if suggested_group and suggested_group.lower() not in ["current liabilities", "sundry debtors"]:
                    warnings.append(f"Customer advance should be classified under 'Current Liabilities', currently under '{suggested_group}'.")

        if stages["stage_1_balancing"] and stages["stage_2_ledger_identity"] and not any("direction" in e.lower() or "voucher" in e.lower() for e in errors):
            stages["stage_3_business_context"] = True
            stage_details["stage_3"] = f"Passed: Consistent {v_type} direction verified."
        else:
            stage_details["stage_3"] = "Failed: Direction or business context mismatch."

        # =====================================================================
        # STAGE 4: Duplicate Transaction & Idempotency Check
        # =====================================================================
        ref = (tx.bank_reference or "").strip()
        if ref and existing_tx_references and ref in existing_tx_references:
            warnings.append(f"Potential duplicate bank transaction detected with reference '{ref}'.")
            requires_clarification = True
            stage_details["stage_4"] = f"Warning: Duplicate reference '{ref}'."
        else:
            stages["stage_4_duplicate_detection"] = True
            stage_details["stage_4"] = "Passed: Unique transaction verified."

        # =====================================================================
        # STAGE 5: Human Approval Gate
        # =====================================================================
        # Mandatory human approval for:
        # a) Refunds with uncertain accounting nature
        # b) Confidence < 80%
        # c) Suspense Account suggestions
        is_refund_tx = is_refund or "refund" in narr_lower or "reversal" in narr_lower
        is_suspense = t_ledger.lower() in ["suspense", "suspense account"]
        is_low_conf = confidence < 0.80

        if is_refund_tx:
            requires_clarification = True
            warnings.append("Refund transaction requires human verification of refund nature (Customer vs Vendor vs Tax).")
            stage_details["stage_5"] = "Awaiting Review: Refund nature verification required."
        elif is_suspense:
            requires_clarification = True
            warnings.append("Transaction mapped to Suspense Account. Requires human ledger assignment.")
            stage_details["stage_5"] = "Awaiting Review: Suspense Account requires manual resolution."
        elif is_low_conf:
            requires_clarification = True
            warnings.append(f"Confidence score {confidence*100:.1f}% is below autonomous threshold (80%).")
            stage_details["stage_5"] = f"Awaiting Review: Confidence {confidence*100:.1f}% < 80%."
        else:
            stages["stage_5_human_approval_gate"] = True
            stage_details["stage_5"] = "Passed: Autonomous approval criteria met."

        # =====================================================================
        # STAGE 6: Final Tally Prime Staging Qualification
        # A balanced voucher does NOT automatically qualify unless Stages 1-5 pass!
        # =====================================================================
        is_valid = (
            stages["stage_1_balancing"] and
            stages["stage_2_ledger_identity"] and
            stages["stage_3_business_context"] and
            stages["stage_4_duplicate_detection"] and
            len(errors) == 0
        )

        can_auto_post = is_valid and stages["stage_5_human_approval_gate"] and not requires_clarification
        stages["stage_6_tally_qualification"] = can_auto_post

        if can_auto_post:
            stage_details["stage_6"] = "Qualified: Cleared all stages for autonomous Tally posting."
        else:
            stage_details["stage_6"] = "Staged: Routing to Clarification Queue for accountant review."

        return {
            "is_valid": is_valid,
            "can_auto_post": can_auto_post,
            "requires_clarification": requires_clarification or not can_auto_post,
            "stages": stages,
            "stage_details": stage_details,
            "errors": errors,
            "warnings": warnings,
            "balanced_entry": {
                "amount": float(amount),
                "primary_ledger": t_ledger,
                "contra_ledger": effective_contra,
                "voucher_type": v_type,
                "suggested_group": suggested_group
            }
        }
