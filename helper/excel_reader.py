import os
import re
import csv
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
from utils.security import calculate_file_hash

DATE_ALIASES = ["date", "transaction date", "txn date", "value date", "trans date", "posting date"]
NARRATION_ALIASES = ["narration", "description", "particulars", "transaction description", "remarks", "details"]
DEBIT_ALIASES = ["debit", "withdrawal", "dr", "debit amount", "withdrawal amt", "dr amount"]
CREDIT_ALIASES = ["credit", "deposit", "cr", "credit amount", "deposit amt", "cr amount"]
REF_ALIASES = ["ref", "reference", "ref no", "reference no", "chq/ref no", "cheque no", "utr", "txn id", "transaction id"]
BALANCE_ALIASES = ["balance", "closing balance", "running balance", "available balance"]


class ExcelReaderService:
    def __init__(self, max_file_size_bytes: int = 25 * 1024 * 1024):
        self.max_file_size_bytes = max_file_size_bytes

    def read_and_validate_file(self, file_path: str) -> Tuple[str, int, bytes]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_size_bytes:
            raise ValueError(f"File size {file_size} exceeds maximum permitted limit {self.max_file_size_bytes} bytes")

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in [".xlsx", ".xls", ".csv"]:
            raise ValueError(f"Unsupported file format '{ext}'. Supported formats: .xlsx, .xls, .csv")

        with open(file_path, "rb") as f:
            content = f.read()

        file_hash = calculate_file_hash(content)
        return file_hash, file_size, content

    def parse_bank_statement(self, file_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".csv":
            return self._parse_csv(file_path)
        else:
            return self._parse_excel(file_path)

    def _parse_csv(self, file_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Try multiple encodings for CSV
        df = None
        for encoding in ["utf-8", "latin1", "cp1252"]:
            try:
                # Read raw to detect header
                df_raw = pd.read_csv(file_path, header=None, encoding=encoding)
                header_idx = self._find_header_row(df_raw)
                df = pd.read_csv(file_path, skiprows=header_idx, encoding=encoding)
                break
            except Exception:
                continue
        
        if df is None:
            raise ValueError("Could not parse CSV file with standard encodings (utf-8, latin1, cp1252).")

        return self._process_dataframe(df, header_row_index=header_idx if 'header_idx' in locals() else 0)

    def _parse_excel(self, file_path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        excel_file = pd.ExcelFile(file_path)
        sheet_name = excel_file.sheet_names[0]
        
        # Read without header first to detect where the actual transaction table headers begin
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
        header_row_index = self._find_header_row(df_raw)
        
        # Read with appropriate header row
        df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=header_row_index)
        return self._process_dataframe(df, header_row_index=header_row_index)

    def _process_dataframe(self, df: pd.DataFrame, header_row_index: int = 0) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Normalize column names
        normalized_cols = {col: self._clean_col_name(str(col)) for col in df.columns}
        df = df.rename(columns=normalized_cols)

        # Match columns with aliases
        matched_cols = self._match_columns(list(df.columns))

        if not matched_cols.get("date") or not matched_cols.get("narration"):
            raise ValueError("Required columns (Date and Narration/Particulars) could not be identified.")

        valid_transactions = []
        parsing_errors = []

        for idx, row in df.iterrows():
            source_row_num = header_row_index + 2 + idx  # 1-based index matching spreadsheet row
            
            # Skip empty rows
            if row.isna().all():
                continue

            try:
                # Date parsing
                raw_date = row[matched_cols["date"]]
                parsed_date = self._parse_date(raw_date)
                if not parsed_date:
                    continue  # Possibly a summary / footer row

                # Narration parsing
                raw_narration = str(row[matched_cols["narration"]]).strip()
                if not raw_narration or raw_narration.lower() in ["nan", "none", "total", "closing balance"]:
                    continue

                # Amounts
                debit_val = self._parse_decimal(row.get(matched_cols.get("debit"))) if matched_cols.get("debit") else Decimal("0.00")
                credit_val = self._parse_decimal(row.get(matched_cols.get("credit"))) if matched_cols.get("credit") else Decimal("0.00")
                balance_val = self._parse_decimal(row.get(matched_cols.get("balance"))) if matched_cols.get("balance") else None
                ref_val = str(row.get(matched_cols.get("ref"))).strip() if matched_cols.get("ref") and pd.notna(row.get(matched_cols.get("ref"))) else None

                # Clean 'nan' string in ref
                if ref_val and ref_val.lower() == "nan":
                    ref_val = None

                # Must have at least some debit or credit
                if debit_val == Decimal("0.00") and credit_val == Decimal("0.00"):
                    continue

                valid_transactions.append({
                    "source_row_index": source_row_num,
                    "transaction_date": parsed_date,
                    "value_date": parsed_date,
                    "bank_reference": ref_val,
                    "narration": raw_narration,
                    "debit_amount": debit_val,
                    "credit_amount": credit_val,
                    "balance": balance_val,
                    "raw_payload": {str(k): (str(v) if pd.notna(v) else None) for k, v in row.items()}
                })

            except Exception as e:
                parsing_errors.append({
                    "row_index": source_row_num,
                    "error": str(e),
                    "raw_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })

        return valid_transactions, parsing_errors

    def _find_header_row(self, df_raw: pd.DataFrame) -> int:
        for r_idx in range(min(20, len(df_raw))):
            row_str = " ".join([str(val).lower() for val in df_raw.iloc[r_idx] if pd.notna(val)])
            has_date = any(alias in row_str for alias in DATE_ALIASES)
            has_narration = any(alias in row_str for alias in NARRATION_ALIASES)
            if has_date and has_narration:
                return r_idx
        return 0

    def _clean_col_name(self, name: str) -> str:
        name = name.strip().lower()
        name = re.sub(r'[\r\n\t]+', ' ', name)
        name = re.sub(r'[^a-z0-9 /._-]', '', name)
        return name

    def _match_columns(self, cols: List[str]) -> Dict[str, Optional[str]]:
        mapping = {"date": None, "narration": None, "debit": None, "credit": None, "ref": None, "balance": None}
        for col in cols:
            for alias in DATE_ALIASES:
                if alias == col or alias in col:
                    if not mapping["date"]:
                        mapping["date"] = col
            for alias in NARRATION_ALIASES:
                if alias == col or alias in col:
                    if not mapping["narration"]:
                        mapping["narration"] = col
            for alias in DEBIT_ALIASES:
                if alias == col or alias in col:
                    if not mapping["debit"]:
                        mapping["debit"] = col
            for alias in CREDIT_ALIASES:
                if alias == col or alias in col:
                    if not mapping["credit"]:
                        mapping["credit"] = col
            for alias in REF_ALIASES:
                if alias == col or alias in col:
                    if not mapping["ref"]:
                        mapping["ref"] = col
            for alias in BALANCE_ALIASES:
                if alias == col or alias in col:
                    if not mapping["balance"]:
                        mapping["balance"] = col
        return mapping

    def _parse_date(self, val: Any) -> Optional[date]:
        if pd.isna(val):
            return None
        if isinstance(val, (datetime, pd.Timestamp)):
            return val.date()
        if isinstance(val, date):
            return val
        val_str = str(val).strip()
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d/%m/%y", "%m/%d/%Y"):
            try:
                return datetime.strptime(val_str, fmt).date()
            except ValueError:
                continue
        try:
            parsed = pd.to_datetime(val_str, dayfirst=True)
            return parsed.date()
        except Exception:
            return None

    def _parse_decimal(self, val: Any) -> Decimal:
        if pd.isna(val) or val is None:
            return Decimal("0.00")
        if isinstance(val, (int, float)):
            return Decimal(str(round(val, 2)))
        val_str = str(val).strip()
        val_str = re.sub(r'[₹$,Rs.INR\s]', '', val_str)
        if not val_str or val_str.lower() in ["-", "nil", "nan"]:
            return Decimal("0.00")
        try:
            return Decimal(val_str).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")

