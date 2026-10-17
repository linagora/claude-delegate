from __future__ import annotations

import unittest

from qrg_pilot.c1_internal.changelog import group_by_type


class GroupByTypeTest(unittest.TestCase):
    def test_subjects_are_grouped_by_type_in_order(self) -> None:
        groups = group_by_type(["feat: route tasks", "fix(router): keep the class", "feat!: drop v0"])
        self.assertEqual(groups, {"feat": ["route tasks", "drop v0"], "fix": ["keep the class"]})

    def test_a_free_form_subject_lands_under_other(self) -> None:
        self.assertEqual(group_by_type(["Merge branch 'main'"]), {"other": ["Merge branch 'main'"]})
