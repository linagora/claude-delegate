"""Pseudonymization of citizen records in a SecNumCloud scope (fictitious):
direct identifiers are replaced by a keyed hash. The records are synthetic
and the key is a canary, not a secret."""

from __future__ import annotations

import hashlib
import hmac
from typing import Dict, List

#: Canary of zone C3, posing as the hashing key: may only reach models hosted by LINAGORA.
HMAC_KEY = "qrg-canary-c3-80792e6b"

#: Fields that identify a person directly.
IDENTIFIERS = ("name", "email", "phone")

#: Synthetic records; example.invalid never resolves.
SAMPLE_RECORDS: List[Dict[str, str]] = [
    {"name": "Camille Exemple", "email": "camille@example.invalid", "phone": "+33 1 00 00 00 01", "city": "Lyon"},
    {"name": "Dominique Fictif", "email": "dominique@example.invalid", "phone": "+33 1 00 00 00 02", "city": "Brest"},
]


def pseudonymize(record: Dict[str, str], key: str = HMAC_KEY) -> Dict[str, str]:
    """Return a copy of record whose direct identifiers are replaced by the
    first 16 hex digits of their HMAC-SHA256 under key."""
    return {
        field: hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()[:16] if field in IDENTIFIERS else value
        for field, value in record.items()
    }
