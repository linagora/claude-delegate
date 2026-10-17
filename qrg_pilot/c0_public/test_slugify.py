from __future__ import annotations

import unittest

from qrg_pilot.c0_public.slugify import slugify


class SlugifyTest(unittest.TestCase):
    def test_accents_are_folded_and_spaces_become_hyphens(self) -> None:
        self.assertEqual(slugify("Énoncé du marché"), "enonce-du-marche")

    def test_runs_of_punctuation_collapse_and_ends_are_trimmed(self) -> None:
        self.assertEqual(slugify("  QRG: lot 1 -- routage!  "), "qrg-lot-1-routage")
