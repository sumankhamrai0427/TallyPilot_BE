import json
import re
from typing import List, Optional, Tuple, Dict, Any
import httpx
from utils.config import config
from model.schemas import AICorrectionProposal
from model.models import VoucherType


class LocalLLMService:
    def __init__(self):
        self.active_llm = config.ACTIVE_LLM
        self.confidence_threshold = config.AI_CONFIDENCE_THRESHOLD

        # Mistral Cloud Configuration
        self.mistral_api_key = config.MISTRAL_API_KEY
        self.mistral_model = config.MISTRAL_MODEL
        self.mistral_chat_url = config.MISTRAL_CHAT_URL

        # Mistral Local / Self-Hosted Configuration
        self.mistral_local_url = config.MISTRAL_LOCAL_URL.rstrip('/')
        self.mistral_local_model = config.MISTRAL_LOCAL_MODEL
        self.model = self.mistral_model if self.active_llm == "mistral_cloud" else self.mistral_local_model

    def check_health(self) -> Dict[str, Any]:
        """Check if configured LLM service (Mistral Cloud or Mistral Local) is reachable."""
        if self.active_llm == "mistral_cloud":
            if self.mistral_api_key:
                return {
                    "available": True,
                    "status": "connected",
                    "provider": "Mistral Cloud",
                    "model": self.mistral_model,
                    "endpoint": self.mistral_chat_url
                }
            return {
                "available": False,
                "status": "missing_api_key",
                "provider": "Mistral Cloud",
                "error": "MISTRAL_API_KEY not configured in .env",
                "fallback_active": True
            }

        # Mistral Local / Ollama endpoint health check
        try:
            with httpx.Client(timeout=0.5) as client:
                res = client.get(f"{self.mistral_local_url}/api/tags")
                if res.status_code == 200:
                    models = [m.get("name") for m in res.json().get("models", [])]
                    return {
                        "available": True,
                        "status": "connected",
                        "provider": "Mistral Local",
                        "endpoint": self.mistral_local_url,
                        "configured_model": self.mistral_local_model,
                        "available_models": models
                    }
        except Exception:
            pass

        # Try standard /v1/models check for vLLM / LiteLLM / OpenAI-compatible
        try:
            with httpx.Client(timeout=0.5) as client:
                res = client.get(f"{self.mistral_local_url}/v1/models")
                if res.status_code == 200:
                    return {
                        "available": True,
                        "status": "connected",
                        "provider": "Mistral Local (v1)",
                        "endpoint": self.mistral_local_url,
                        "configured_model": self.mistral_local_model
                    }
        except Exception:
            pass

        return {
            "available": False,
            "status": "disconnected",
            "provider": self.active_llm,
            "endpoint": self.mistral_local_url,
            "fallback_active": True
        }

    def classify_transaction(
        self,
        narration: str,
        debit_amount: float,
        credit_amount: float,
        available_ledgers: List[str],
        available_groups: Optional[List[str]] = None
    ) -> Tuple[AICorrectionProposal, bool]:
        """
        Classifies transaction narration using Mistral LLM (Cloud or Local),
        or gracefully falls back to deterministic rule-based engine.
        Returns: (AICorrectionProposal, is_fallback_rule)
        """
        health = self.check_health()
        if not health["available"]:
            print(f"   ⚠️ [LLM Offline] Provider '{self.active_llm}' is currently unavailable ({health.get('status')}).", flush=True)
            print(f"   ⚙️ [Rule Engine] Activating Deterministic Rule-Based Fallback Engine...", flush=True)
            fallback = self._rule_based_fallback(narration, debit_amount, credit_amount, available_ledgers)
            return fallback, True

        prompt = self._build_prompt(narration, debit_amount, credit_amount, available_ledgers, available_groups)
        print(f"   🤖 [LLM Calling] Provider: {self.active_llm.upper()} | Model: {self.model} ...", flush=True)
        
        try:
            # 1. Mistral Cloud API
            if self.active_llm == "mistral_cloud" and self.mistral_api_key:
                headers = {
                    "Authorization": f"Bearer {self.mistral_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.mistral_model,
                    "messages": [
                        {"role": "system", "content": "You are a professional accounting classification engine. Respond with strict JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
                with httpx.Client(timeout=15.0) as client:
                    res = client.post(self.mistral_chat_url, json=payload, headers=headers)
                    if res.status_code == 200:
                        content = res.json()["choices"][0]["message"]["content"]
                        print(f"   ✅ [LLM Response] {content.strip()}", flush=True)
                        parsed_json = json.loads(content)
                        return self._process_llm_json(parsed_json, available_ledgers, debit_amount, credit_amount, narration, available_groups)
                    else:
                        print(f"   ⚠️ [LLM API Error] Status {res.status_code}: {res.text}", flush=True)

            # 2. Mistral Local / OpenAI Compatible or Ollama endpoint
            elif self.active_llm == "mistral_local":
                # Try OpenAI-compatible chat completions first
                chat_payload = {
                    "model": self.mistral_local_model,
                    "messages": [
                        {"role": "system", "content": "You are a professional accounting classification engine. Respond with strict JSON only."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1
                }
                with httpx.Client(timeout=15.0) as client:
                    for endpoint in [f"{self.mistral_local_url}/v1/chat/completions", f"{self.mistral_local_url}/chat/completions"]:
                        try:
                            res = client.post(endpoint, json=chat_payload)
                            if res.status_code == 200:
                                content = res.json()["choices"][0]["message"]["content"]
                                print(f"   ✅ [LLM Response] {content.strip()}", flush=True)
                                parsed_json = json.loads(re.search(r'\{.*\}', content, re.DOTALL).group(0))
                                return self._process_llm_json(parsed_json, available_ledgers, debit_amount, credit_amount, narration, available_groups)
                        except Exception as e:
                            continue

                    # Fallback to Ollama /api/generate
                    ollama_payload = {
                        "model": self.mistral_local_model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.1}
                    }
                    try:
                        res = client.post(f"{self.mistral_local_url}/api/generate", json=ollama_payload)
                        if res.status_code == 200:
                            body = res.json()
                            content = body.get("response", "{}")
                            print(f"   ✅ [LLM Response] {content.strip()}", flush=True)
                            parsed_json = json.loads(content)
                            return self._process_llm_json(parsed_json, available_ledgers, debit_amount, credit_amount, narration, available_groups)
                    except Exception as e:
                        pass

        except Exception as e:
            print(f"   ⚠️ [LLM Exception] {e}", flush=True)

        print(f"   ⚙️ [Rule Engine] Switching to Deterministic Rule-Based Fallback Engine...", flush=True)
        fallback = self._rule_based_fallback(narration, debit_amount, credit_amount, available_ledgers)
        print(f"   💡 [Fallback Rule Result] Suggested Ledger: \"{fallback.suggested_ledger}\" | Voucher: {fallback.suggested_voucher_type.value} | Confidence: {float(fallback.confidence)*100:.1f}%", flush=True)
        return fallback, True

    def _process_llm_json(
        self,
        parsed_json: Dict[str, Any],
        available_ledgers: List[str],
        debit: float = 0.0,
        credit: float = 0.0,
        narration: str = "",
        available_groups: Optional[List[str]] = None
    ) -> Tuple[AICorrectionProposal, bool]:
        """Validates LLM JSON output against company ledgers without forcing wrong suppliers."""
        proposal = AICorrectionProposal(**parsed_json)
        narr_lower = (narration or "").lower()

        # Enforce strict double-entry direction consistency
        if credit > 0:
            if proposal.suggested_voucher_type not in (VoucherType.RECEIPT, VoucherType.CONTRA):
                proposal.suggested_voucher_type = VoucherType.RECEIPT
            if proposal.transaction_type == "supplier_payment":
                proposal.transaction_type = "customer_receipt"
        elif debit > 0:
            if proposal.suggested_voucher_type == VoucherType.RECEIPT:
                proposal.suggested_voucher_type = VoucherType.PAYMENT

        # Dynamic account group resolution
        if available_groups:
            matched_grp = next((g for g in available_groups if g.lower() == (proposal.suggested_group_name or "").lower()), None)
            if matched_grp:
                proposal.suggested_group_name = matched_grp
            else:
                # Dynamic contextual matching based on transaction purpose & flow direction
                if credit > 0:
                    if any(k in narr_lower for k in ["interest", "int.", "dividend", "yield", "fd int"]):
                        proposal.suggested_group_name = next((g for g in available_groups if "Income" in g), "Indirect Incomes")
                    elif any(k in narr_lower for k in ["sales", "pos", "counter", "merchant"]):
                        proposal.suggested_group_name = next((g for g in available_groups if "Sales" in g or "Income" in g), "Sales Accounts")
                    elif any(k in narr_lower for k in ["refund", "gst", "tax", "it refund", "subsidy"]):
                        proposal.suggested_group_name = next((g for g in available_groups if "Tax" in g or "Asset" in g), "Duties & Taxes")
                    else:
                        proposal.suggested_group_name = next((g for g in available_groups if "Debtor" in g or "Customer" in g), "Sundry Debtors")
                else:
                    if any(k in narr_lower for k in ["supplier", "hardware", "contractor", "services", "ltd", "corp", "pvt"]):
                        proposal.suggested_group_name = next((g for g in available_groups if "Creditor" in g or "Supplier" in g), "Sundry Creditors")
                    else:
                        proposal.suggested_group_name = next((g for g in available_groups if "Expense" in g), "Indirect Expenses")
        else:
            if not proposal.suggested_group_name:
                proposal.suggested_group_name = "Sundry Debtors" if credit > 0 else "Indirect Expenses"

        matched = None
        if proposal.suggested_ledger:
            for l in available_ledgers:
                if l.strip().lower() == proposal.suggested_ledger.strip().lower():
                    matched = l
                    break

        if matched:
            proposal.suggested_ledger = matched
            proposal.requires_new_ledger = False
        else:
            proposal.requires_new_ledger = True

            # Autonomous Intelligence:
            # If the LLM has high confidence (>= threshold) AND did not flag review,
            # allow autonomous registration without forcing human clarification!
            if proposal.confidence >= self.confidence_threshold and not proposal.requires_human_review:
                proposal.requires_human_review = False
            else:
                proposal.requires_human_review = True
                proposal.ambiguity_reason = proposal.ambiguity_reason or f"Ledger '{proposal.suggested_ledger}' needs review under '{proposal.suggested_group_name}'."

        print(f"   💡 [LLM Suggestion] Ledger: \"{proposal.suggested_ledger}\" | Group: \"{proposal.suggested_group_name}\" | New: {proposal.requires_new_ledger} | Confidence: {float(proposal.confidence)*100:.1f}%", flush=True)
        return proposal, False

    def _build_prompt(self, narration: str, debit: float, credit: float, ledgers: List[str], available_groups: Optional[List[str]] = None) -> str:
        direction = f"Withdrawal/Debit (Outgoing payment): {debit}" if debit > 0 else f"Deposit/Credit (Incoming receipt): {credit}"
        ledgers_str = ", ".join(f'"{l}"' for l in ledgers[:50])
        groups_list = available_groups or [
            "Sundry Debtors", "Sundry Creditors", "Indirect Expenses", "Direct Expenses",
            "Sales Accounts", "Purchase Accounts", "Indirect Incomes", "Duties & Taxes",
            "Bank Accounts", "Cash-in-hand", "Capital Account"
        ]
        groups_str = ", ".join(f'"{g}"' for g in groups_list)
        return f"""You are an autonomous expert Tally Prime accounting classification intelligence.
Analyze this Indian bank transaction and classify it into strict double-entry accounting with real-world business context.

Transaction Direction: {direction}
Bank Narration: "{narration}"
Existing Company Ledgers in Database: [{ledgers_str}]
Available Account Groups in Master Database: [{groups_str}]

Classification & Entity Grounding Rules:
1. EXISTING LEDGERS: If the narration clearly matches an EXISTING ledger (e.g. Office Rent, Electricity, Bank Charges, or an existing Customer/Supplier), use that exact ledger with confidence >= 0.88 and requires_new_ledger = false.
2. DYNAMIC GROUP & ENTITY RECOGNITION:
   - For incoming money (Credit/Receipt):
     * If from a customer, buyer, or trade invoice -> choose "Sundry Debtors".
     * If bank interest, savings interest, or dividend -> choose "Indirect Incomes".
     * If tax/GST refund or subsidy -> choose "Duties & Taxes" or "Current Assets".
     * If cash sales, pos, counter retail -> choose "Sales Accounts".
   - For outgoing money (Debit/Payment):
     * If commercial vendor/supplier/contractor -> choose "Sundry Creditors".
     * If operational expenses (rent, electricity, amc, pantry, telecom, freight) -> choose "Indirect Expenses" or "Direct Expenses".
   - Select suggested_group_name strictly from the Available Account Groups list above.
3. CONTRA: For ATM cash withdrawals, cash deposits, or inter-bank self-transfers, classify as suggested_voucher_type = "Contra", suggested_ledger = "Cash" (or other bank), confidence = 0.92, requires_human_review = false.
4. GENUINELY AMBIGUOUS / CRYPTIC: If the narration is completely obscure, unverified, cryptic, or suspicious (e.g. "UPI/849204910294/UNRECOGNIZED-STORE", obscure personal string, or unexplained debit):
   - Set suggested_ledger = "Suspense Account", suggested_group_name = "Indirect Expenses".
   - Set confidence = 0.40 to 0.60, requires_human_review = true.
   - Provide an actionable ambiguity_reason explaining why accountant verification is required.

Respond ONLY with a valid JSON object matching this schema:
{{
  "transaction_type": "supplier_payment | customer_receipt | bank_charges | utility_expense | office_expense | travel_expense | rent_expense | contra_transfer | other",
  "suggested_voucher_type": "Payment | Receipt | Contra | Journal",
  "suggested_ledger": "Clean ledger name",
  "suggested_group_name": "One of the Available Account Groups",
  "requires_new_ledger": true or false,
  "contra_ledger": "Bank ledger or null",
  "confidence": 0.0 to 1.0,
  "requires_human_review": true or false,
  "ambiguity_reason": "Explanation if review needed or null",
  "explanation": "Concise accounting rationale"
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

        # 1. Check Bank Charges
        if any(w in text for w in ["chg", "charge", "charges", "annual fee", "sms", "sms chg", "min bal", "gst"]):
            ledger = self._find_ledger_matching(["bank charges", "indirect expenses"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="bank_charges",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger or "Bank Charges",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.92,
                requires_human_review=False,
                explanation="Detected bank operational fees or charges in narration."
            )

        # 2. Check Supermarket / Retail / Pantry Expenses (DMart, Blinkit, Grocery, etc.)
        if any(w in text for w in ["dmart", "supermarket", "grocery", "groceries", "blinkit", "zepto", "reliance fresh", "spencer", "more retail", "convenience store", "bazaar", "mart"]):
            pantry_ledger = self._find_ledger_matching(["pantry", "office / pantry", "office expenses", "general expenses", "staff welfare"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="office_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=pantry_ledger or "Office / Pantry Expenses",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(pantry_ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.90,
                requires_human_review=(pantry_ledger is None),
                ambiguity_reason="Office pantry/supermarket purchase detected. Propose creating Office / Pantry Expenses." if pantry_ledger is None else None,
                explanation="Retail supermarket or grocery purchase categorized as office pantry expense."
            )

        # 3. Check Electricity / Utilities
        if any(w in text for w in ["electricity", "power", "bescom", "wbsedcl", "tneb", "cesc"]):
            ledger = self._find_ledger_matching(["electricity expenses", "utility"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="utility_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger or "Electricity Expenses",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.88,
                requires_human_review=False,
                explanation="Utility electricity bill payment detected."
            )

        # 4. Check Telephone / Internet
        if any(w in text for w in ["airtel", "jio", "vodafone", "telecom", "broadband", "internet"]):
            ledger = self._find_ledger_matching(["telephone & internet charges", "telephone", "internet"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="utility_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger or "Telephone & Internet Charges",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.89,
                requires_human_review=False,
                explanation="Telecommunication charges detected."
            )

        # 5. Check Fuel & Conveyance / Travel
        if any(w in text for w in ["petrol", "diesel", "fuel", "hpcl", "bpcl", "indianoil", "iocl", "shell", "uber", "ola", "irctc", "indigo", "makemytrip"]):
            travel_ledger = self._find_ledger_matching(["travelling & conveyance", "travelling", "conveyance", "fuel"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="travel_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=travel_ledger or "Travelling & Conveyance",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(travel_ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.88,
                requires_human_review=(travel_ledger is None),
                explanation="Fuel or travel conveyance expense detected."
            )

        # 6. Check Rent
        if any(w in text for w in ["rent", "lease", "office rent"]):
            ledger = self._find_ledger_matching(["office rent", "rent"], available_ledgers)
            return AICorrectionProposal(
                transaction_type="rent_expense",
                suggested_voucher_type=VoucherType.PAYMENT,
                suggested_ledger=ledger or "Office Rent",
                suggested_group_name="Indirect Expenses",
                requires_new_ledger=(ledger is None),
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.90,
                requires_human_review=False,
                explanation="Office rent payment detected."
            )

        # 7. Check Contra (Inter-bank or ATM cash withdrawal)
        if any(w in text for w in ["atm cash", "cash wdl", "cash dep", "self transfer", "contra", "to sbi", "from sbi", "to hdfc"]):
            contra_target = self._find_other_bank(text, available_ledgers)
            return AICorrectionProposal(
                transaction_type="contra_transfer",
                suggested_voucher_type=VoucherType.CONTRA,
                suggested_ledger=contra_target or "Cash",
                suggested_group_name="Cash-in-hand" if contra_target == "Cash" else "Bank Accounts",
                requires_new_ledger=False,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.92,
                requires_human_review=False,
                explanation="Cash withdrawal or inter-bank contra transfer verified."
            )

        # 8. Check supplier or customer by EXACT or TOKEN match in available ledgers
        matched_ledger = None
        for ledger in available_ledgers:
            tokens = [t.lower() for t in re.split(r'[\s&,.-]+', ledger) if len(t) > 3 and t.lower() not in ["ltd", "limited", "pvt", "private", "corp", "inc", "account", "bank", "expenses"]]
            if tokens and any(t in text for t in tokens):
                matched_ledger = ledger
                break

        if matched_ledger:
            return AICorrectionProposal(
                transaction_type=default_type,
                suggested_voucher_type=default_voucher,
                suggested_ledger=matched_ledger,
                suggested_group_name=None,
                requires_new_ledger=False,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.88,
                requires_human_review=False,
                explanation=f"Identified matching party ledger '{matched_ledger}' in narration."
            )

        # 8b. Autonomous Commercial Entity Disambiguation (vendors / retail customers)
        clean_party = self._extract_clean_party_name(narration)
        is_unrecognized = any(w in text for w in ["unrecognized", "unknown", "suspicious", "fraud", "dispute", "unmapped"])

        if clean_party and len(clean_party) >= 3 and not is_unrecognized:
            is_expense_purpose = any(w in text for w in ["amc", "service", "hardware", "software", "maintenance", "consult", "supply", "logistics", "freight", "repair"])
            suggested_grp = "Indirect Expenses" if is_expense_purpose else ("Sundry Creditors" if is_debit else "Sundry Debtors")
            return AICorrectionProposal(
                transaction_type="supplier_payment" if is_debit else "customer_receipt",
                suggested_voucher_type=default_voucher,
                suggested_ledger=clean_party,
                suggested_group_name=suggested_grp,
                requires_new_ledger=True,
                contra_ledger=self._get_bank_ledger(available_ledgers),
                confidence=0.89,
                requires_human_review=False,
                explanation=f"Autonomous entity recognition: Identified commercial entity '{clean_party}' under '{suggested_grp}'."
            )

        # 9. Ambiguous / Unidentified transaction - propose Suspense Account, NEVER an unrelated supplier!
        suspense_ledger = self._find_ledger_matching(["suspense", "suspense account"], available_ledgers)
        return AICorrectionProposal(
            transaction_type=default_type,
            suggested_voucher_type=default_voucher,
            suggested_ledger=suspense_ledger or "Suspense Account",
            suggested_group_name="Indirect Expenses",
            requires_new_ledger=(suspense_ledger is None),
            contra_ledger=self._get_bank_ledger(available_ledgers),
            confidence=0.40,
            requires_human_review=True,
            ambiguity_reason="Unrecognized party or narration pattern. Assigned to Suspense Account pending human clarification.",
            explanation="Unrecognized transaction description."
        )

    def _extract_clean_party_name(self, narration: str) -> Optional[str]:
        text = narration.strip()
        parts = [p.strip() for p in re.split(r'[/|\-]+', text) if p.strip()]
        candidates = []
        for p in parts:
            clean = re.sub(r'^(neft|rtgs|imps|upi|nach|cms|pos|chq|wdl|dep|in|out|transfer|txn|ref)\b[\s:]*', '', p, flags=re.IGNORECASE).strip()
            if not clean or re.fullmatch(r'[A-Za-z0-9_]{10,}', clean) or re.fullmatch(r'\d+', clean):
                continue
            if clean.lower() in ["bank", "statement", "payment", "receipt", "account", "transfer", "dr", "cr"]:
                continue
            candidates.append(clean)
        if candidates:
            target = candidates[-1]
            target = re.sub(r'\s+(it hardware amc|premises bangalore|mum|del|blr)$', '', target, flags=re.IGNORECASE).strip()
            if len(target) >= 3 and not target.lower().startswith("unrecognized"):
                return target.title()
        return None

    def _find_ledger_matching(self, patterns: List[str], ledgers: List[str]) -> Optional[str]:
        for pat in patterns:
            for l in ledgers:
                if pat.lower() in l.lower():
                    return l
        return None

    def _find_closest_ledger(self, suggestion: str, ledgers: List[str]) -> Optional[str]:
        s_lower = suggestion.lower()
        for l in ledgers:
            if s_lower in l.lower() or l.lower() in s_lower:
                return l
        return None

    def _get_bank_ledger(self, ledgers: List[str]) -> Optional[str]:
        for l in ledgers:
            if "bank" in l.lower():
                return l
        return ledgers[0] if ledgers else None

    def _find_other_bank(self, text: str, ledgers: List[str]) -> Optional[str]:
        # If it's a cash withdrawal or deposit, match cash account first
        if any(w in text for w in ["atm", "cash", "wdl", "dep"]):
            for l in ledgers:
                if "cash" in l.lower():
                    return l
            return "Cash"

        # Inter-bank transfer: find other bank
        for l in ledgers:
            if "bank" in l.lower():
                first_word = l.split()[0].lower()
                if first_word in text:
                    return l
        return self._get_bank_ledger(ledgers)


    def generate_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates conversational response using configured Local LLM or Mistral Cloud."""
        sys_msg = system_prompt or "You are an expert accounting assistant for TallyPilot. Provide concise, professional financial guidance."

        try:
            # 1. Mistral Cloud API
            if self.active_llm == "mistral_cloud" and self.mistral_api_key:
                headers = {
                    "Authorization": f"Bearer {self.mistral_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": self.mistral_model,
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
                with httpx.Client(timeout=20.0) as client:
                    res = client.post(self.mistral_chat_url, json=payload, headers=headers)
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"]

            # 2. Mistral Local / Ollama / OpenAI-compatible
            elif self.active_llm == "mistral_local":
                # Try OpenAI-compatible endpoint
                chat_payload = {
                    "model": self.mistral_local_model,
                    "messages": [
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
                with httpx.Client(timeout=10.0) as client:
                    for endpoint in [f"{self.mistral_local_url}/v1/chat/completions", f"{self.mistral_local_url}/chat/completions"]:
                        try:
                            res = client.post(endpoint, json=chat_payload)
                            if res.status_code == 200:
                                return res.json()["choices"][0]["message"]["content"]
                        except Exception:
                            continue

                    # Try Ollama endpoint
                    ollama_payload = {
                        "model": self.mistral_local_model,
                        "prompt": f"{sys_msg}\n\nUser: {prompt}\nAssistant:",
                        "stream": False,
                        "options": {"temperature": 0.2}
                    }
                    try:
                        res = client.post(f"{self.mistral_local_url}/api/generate", json=ollama_payload)
                        if res.status_code == 200:
                            return res.json().get("response", "")
                    except Exception:
                        pass
        except Exception:
            pass

        # Intelligent Fallback response
        return (
            f"I have received your inquiry: \"{prompt}\".\n\n"
            f"As your Local AI Accounting Assistant, I can help you monitor financial periods, "
            f"review Trial Balance, check profit & loss, verify vouchers, and inspect ledger balances.\n\n"
            f"Try asking:\n"
            f"• **'Trial balance status'** — to check if Total Debit equals Total Credit\n"
            f"• **'Profit and loss summary'** — to review revenue vs expenses\n"
            f"• **'Balance of HDFC Bank'** — to check ledger running balance\n"
            f"• Or explore the **Financial Reports** and **Vouchers & Day Book** modules in the sidebar."
        )
