from __future__ import annotations

import json
import unittest
from typing import Any, Dict

from tests.support import FeatureBranchTestCase, success

QUOTA_EXHAUSTED = 4
REVIEW_INCOMPLETE = 5
INVALID_OUTPUT = 6
DELEGATE_FAILURE = 7


def failed(**fields: Any) -> Dict[str, Any]:
    """A `claude -p` result reporting an error."""
    return {**success(), "is_error": True, **fields}


class FailureTest(FeatureBranchTestCase):
    def assert_failure(self, exit_code: int, message: str) -> None:
        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, exit_code, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(list(self.sb.state.rglob("*.md")), [])

    def test_every_usage_limit_wording_is_an_exhausted_quota_with_its_reset_time(self) -> None:
        for wording, expected in [
            (
                "You've hit your weekly limit · resets Oct 6 at 10am (Europe/Paris)",
                "quota Claude épuisé (reprise : Oct 6 at 10am (Europe/Paris))",
            ),
            ("You're out of extra usage · resets 3pm", "quota Claude épuisé (reprise : 3pm)"),
            ("5-hour limit reached ∙ resets 3pm\nUpgrade for more usage", "quota Claude épuisé (reprise : 3pm)"),
        ]:
            with self.subTest(wording):
                self.sb.fake.reply(failed(subtype="success", terminal_reason="api_error", result=wording), 1)

                self.assert_failure(QUOTA_EXHAUSTED, expected)

    def test_an_exhausted_quota_without_reset_time_says_so_plainly(self) -> None:
        self.sb.fake.reply(failed(subtype="success", result="Claude usage limit reached."), 1)

        self.assert_failure(QUOTA_EXHAUSTED, "quota Claude épuisé\n")

    def test_a_throttled_request_keeps_its_original_message(self) -> None:
        self.sb.fake.reply(failed(subtype="success", api_error_status=429, result="Rate limited, retry later"), 1)

        self.assert_failure(QUOTA_EXHAUSTED, "Rate limited, retry later")

    def test_a_review_stopped_by_its_budget_is_incomplete(self) -> None:
        self.sb.fake.reply(failed(subtype="error_max_budget_usd", terminal_reason="budget_exhausted"), 1)

        self.assert_failure(REVIEW_INCOMPLETE, "revue incomplète : plafond de budget atteint")

    def test_a_review_stopped_by_its_turn_limit_is_incomplete(self) -> None:
        self.sb.fake.reply(failed(subtype="error_max_turns"), 1)

        self.assert_failure(REVIEW_INCOMPLETE, "revue incomplète : nombre maximal de tours atteint")

    def test_a_structured_output_off_schema_is_an_invalid_output(self) -> None:
        self.sb.fake.reply(success(findings=[{"severity": "critique"}]))

        self.assert_failure(INVALID_OUTPUT, "sortie structurée")

    def test_any_other_error_is_a_delegate_failure(self) -> None:
        for name, stdout, code in [
            ("erreur signalée", json.dumps(failed(result="Internal server error")), 1),
            ("sortie illisible", "Error: something broke", 1),
        ]:
            with self.subTest(name):
                self.sb.fake.reply_raw(stdout, code)

                self.assert_failure(DELEGATE_FAILURE, "claude-delegate : ")


if __name__ == "__main__":
    unittest.main()
