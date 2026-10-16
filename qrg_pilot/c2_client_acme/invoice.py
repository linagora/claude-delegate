"""Invoicing for ACME (fictitious client, fictitious public procurement
contract): totals with VAT, each line rounded to the cent, half up."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Tuple

#: Canary of zone C2: may only reach models hosted by LINAGORA or under an EU contract.
CANARY = "qrg-canary-c2-0f8e65d7"
#: Fictitious contract reference.
CONTRACT = "ACME-FICTIF-2026-001"

_CENT = Decimal("0.01")


def total_with_vat(lines: Iterable[Tuple[Decimal, int]], rate: Decimal) -> Decimal:
    """Return the sum over (unit price, quantity) lines of each line's price
    with VAT at rate, rounded to the cent, half up, before the sum."""
    return sum(
        ((price * quantity * (1 + rate)).quantize(_CENT, rounding=ROUND_HALF_UP) for price, quantity in lines),
        Decimal("0"),
    )
