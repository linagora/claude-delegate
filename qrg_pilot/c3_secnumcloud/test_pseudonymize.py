from __future__ import annotations

import unittest

from qrg_pilot.c3_secnumcloud.pseudonymize import IDENTIFIERS, SAMPLE_RECORDS, pseudonymize


class PseudonymizeTest(unittest.TestCase):
    def test_direct_identifiers_are_hashed_and_other_fields_kept(self) -> None:
        original = SAMPLE_RECORDS[0]
        record = pseudonymize(original)
        self.assertEqual(record["city"], original["city"])
        for field in IDENTIFIERS:
            self.assertRegex(record[field], r"^[0-9a-f]{16}$")
            self.assertNotEqual(record[field], original[field])

    def test_another_key_gives_another_pseudonym(self) -> None:
        original = SAMPLE_RECORDS[1]
        self.assertNotEqual(pseudonymize(original, "k1")["name"], pseudonymize(original, "k2")["name"])
