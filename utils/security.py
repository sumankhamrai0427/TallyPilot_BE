"""Cryptographic and security utilities for TallyPilot."""
import hashlib
from typing import Union


def calculate_file_hash(file_bytes: bytes) -> str:
    """Computes SHA-256 checksum for bank statement file deduplication."""
    hasher = hashlib.sha256()
    hasher.update(file_bytes)
    return hasher.hexdigest()


def calculate_row_hash(batch_id: int, row_index: int, date_str: str, desc: str, amount_str: str) -> str:
    """Computes SHA-256 fingerprint for a single transaction row to detect duplicates."""
    payload = f"{batch_id}|{row_index}|{date_str}|{desc.strip().lower()}|{amount_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

