import json
import re
from typing import List, Optional, Tuple, Dict, Any
import httpx
from utils.config import config
from model.schemas import AICorrectionProposal
from model.models import VoucherType


class LocalLLMService:
    def __init__(self):
        self.base_url = config.OLLAMA_URL.rstrip('/')
        self.model = config.OLLAMA_MODEL
        self.confidence_threshold = config.AI_CONFIDENCE_THRESHOLD

    def check_health(self) -> Dict[str, Any]:
        """Check if Ollama service is reachable and list models."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    return {
                        "available": True,
                        "status": "connected",
                        "endpoint": self.base_url,
                        "configured_model": self.model,
                        "available_models": models
                    }
        except Exception as e:
            return {
                "available": False,
                "status": "disconnected",
                "endpoint": self.base_url,
                "error": str(e),
                "configured_model": self.model,
                "fallback_active": True
            }
        return {
            "available": False,
            "status": "unreachable",
            "endpoint": self.base_url,
            "fallback_active": True
        }

    def classify_transaction(
        self,
        narration: str,
        debit_amount: float,
        credit_amount: float,
        available_ledgers: List[str]
    ) -> Tuple[AICorrectionProposal, bool]:
        """
        Classifies transaction narration using Ollama LLM,
        or gracefully falls back to deterministic rule-based engine.
        Returns: (AICorrectionProposal, is_fallback_rule)
        """
        health = self.check_health()
        if not health["available"]:
            fallback = self._rule_based_fallback(narration, debit_amount, credit_amount, available_ledgers)
            return fallback, True

        prompt = self._build_prompt(narration, debit_amount, credit_amount, available_ledgers)
        
        try:
            with httpx.Client(timeout=15.0) as client:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {
                        "temperature": 0.1
                    }
                }
                res = client.post(f"{self.base_url}/api/generate", json=payload)
                if res.status_code == 200:
                    body = res.json()
                    response_text = body.get("response", "{}")
                    parsed_json = json.loads(response_text)
                    
                    proposal = AICorrectionProposal(**parsed_json)
                    
                    if proposal.suggested_ledger and proposal.suggested_ledger not in available_ledgers:
                        closest = self._find_closest_ledger(proposal.suggested_ledger, available_ledgers)
                        proposal.suggested_ledger = closest
                        proposal.confidence = min(proposal.confidence, 0.70)
                        proposal.requires_human_review = True
                        proposal.ambiguity_reason = f"Original suggestion '{parsed_json.get('suggested_ledger')}' not in Tally ledgers. Closest match '{closest}' requires confirmation."

                    return proposal, False

        except Exception:
            pass

        fallback = self._rule_based_fallback(narration, debit_amount, credit_amount, available_ledgers)
        return fallback, True

    def _build_prompt(self, narration: str, debit: float, credit: float, ledgers: List[str]) -> str:
        direction = f"Withdrawal/Debit: {debit}" if debit > 0 else f"Deposit/Credit: {credit}"
        ledgers_str = ", ".join(f'"{l}"' for l in ledgers[:40])
        return f"""You are an expert Tally Prime accounting classifier.
Analyze the following bank transaction description and classify it strictly into JSON format.

Transaction Direction: {direction}
Narration: "{narration}"
Allowed Tally Ledgers: [{ledgers_str}]

Respond ONLY with a valid JSON object matching this schema:
{{
  "transaction_type": "supplier_payment | customer_receipt | bank_charges | utility_expense | salary_payment | contra_transfer | other",
  "suggested_voucher_type": "Payment | Receipt | Contra | Journal",
  "suggested_ledger": "Must be one of the Allowed Tally Ledgers or null",
  "contra_ledger": "Bank ledger or null",
  "confidence": 0.0 to 1.0,
  "requires_human_review": true or false,
  "ambiguity_reason": "Explanation if uncertain or null",
  "explanation": "Brief rationale"
}}"""

    def _rule_based_fallback(
        self,
        narration: str,
        debit: float,
        credit: float,
        available_ledgers: List[str]
    ) -> AICorrectionProposal:
        text = narration.lower()
        is_debit = debit > 0

        default_voucher = VoucherType.PAYMENT if is_debit else VoucherType.RECEIPT
        default_type = "supplier_payment" if is_debit else "customer_receipt"

        # Check bank charges
        if any(w in text for w in ["chg", "charge", "charges", "annual fee", "sms chg", "min bal", "gst"]):
            ledger = self._find_ledger_matching(["bank charges", "indirect expenses"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="bank_charges",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.92,
                requires_human_review=False,
                explanation="Detected bank operational fees or charges in narration."
            )

        # Check electricity / utilities
        if any(w in text for w in ["electricity", "power", "bescom", "wbsedcl", "tneb", "cesc"]):
            ledger = self._find_ledger_matching(["electricity expenses", "utility"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="utility_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.88,
                requires_human_review=False,
                explanation="Utility electricity bill payment detected."
            )

        # Check telephone / internet
        if any(w in text for w in ["airtel", "jio", "vodafone", "telecom", "broadband", "internet"]):
            ledger = self._find_ledger_matching(["telephone & internet charges", "telephone"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="utility_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.89,
                requires_human_review=False,
                explanation="Telecommunication charges detected."
            )

        # Check rent
        if any(w in text for w in ["rent", "lease", "office rent"]):
            ledger = self._find_ledger_matching(["office rent", "rent"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="rent_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.90,
                requires_human_review=False,
                explanation="Office rent payment detected."
            )

        # Check Contra (Inter-bank or ATM cash withdrawal)
        if any(w in text for w in ["atm cash", "cash wdl", "cash dep", "self transfer", "contra", "to sbi", "from sbi", "to hdfc"]):
            contra_target = self._find_other_bank(text, available_ledgers)
            return AICorrectionProposal(
                transaction_type="contra_transfer",
                suggested_voucher_type=VoucherType.CONTRA,
                suggested_ledger=contra_target,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.85,
                requires_human_review=True,
                ambiguity_reason="Internal cash/bank transfer requires account verification.",
                explanation="Cash withdrawal or inter-bank contra transfer detected."
            )

        # Check supplier or customer by keywords in available ledgers
        matched_ledger = None
        for ledger in available_ledgers:
            tokens = [t.lower() for t in re.split(r'[\s&,.-]+', ledger) if len(t) > 3 and t.lower() not in ["ltd", "limited", "pvt", "private", "corp", "inc", "account", "bank"]]
            if tokens and any(t in text for t in tokens):
                matched_ledger = ledger
                break

        if matched_ledger:
            return AICorrectionProposal(
                transaction_type=default_type,
                suggested_voucher_type=default_voucher,
                suggested_ledger=matched_ledger,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.85,
                requires_human_review=False,
                explanation=f"Identified matching party ledger '{matched_ledger}' in narration."
            )

        # Ambiguous / Unidentified transaction requiring clarification
        return AICorrectionProposal(
            transaction_type=default_type,
            suggested_voucher_type=default_voucher,
            suggested_ledger=None,
            contra_ledger=self._get_bank_ledger(available_ledgers),
            confidence=0.45,
            requires_human_review=True,
            ambiguity_reason="Unable to determine exact accounting ledger from description. Human clarification required.",
            explanation="Unrecognized party or narration pattern."
        )

    def _find_ledger_matching(self, patterns: List[str], ledgers: List[str]) -> Optional[str]:
        for pat in patterns:
            for l in ledgers:
                if pat.lower() in l.lower():
                    return l
        return ledgers[0] if ledgers else None

    def _find_closest_ledger(self, suggestion: str, ledgers: List[str]) -> Optional[str]:
        s_lower = suggestion.lower()
        for l in ledgers:
            if s_lower in l.lower() or l.lower() in s_lower:
                return l
        return ledgers[0] if ledgers else None

    def _get_bank_ledger(self, ledgers: List[str]) -> Optional[str]:
        for l in ledgers:
            if "bank" in l.lower():
                return l
        return ledgers[0] if ledgers else None

    def _find_other_bank(self, text: str, ledgers: List[str]) -> Optional[str]:
        for l in ledgers:
            if "bank" in l.lower() or "cash" in l.lower():
                first_word = l.split()[0].lower()
                if first_word in text:
                    return l
        return self._get_bank_ledger(ledgers)
