from __future__ import annotations

import unittest
from decimal import Decimal

from qrg_pilot.c2_client_acme.invoice import total_with_vat


class TotalWithVatTest(unittest.TestCase):
    def test_each_line_is_rounded_before_the_sum(self) -> None:
        lines = [(Decimal("1.005"), 1), (Decimal("1.005"), 1)]
        self.assertEqual(total_with_vat(lines, Decimal("0.20")), Decimal("2.42"))

    def test_a_half_cent_rounds_up(self) -> None:
        self.assertEqual(total_with_vat([(Decimal("0.125"), 1)], Decimal("0")), Decimal("0.13"))
