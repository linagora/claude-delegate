from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, Sequence

from tests.support import PLUGIN, SAMPLE_FINDING, FeatureBranchTestCase, option, report_path, success

#: What the original hostile review finds: F1 (bloquant), F2 (important), F3 (mineur).
ORIGINAL_FINDINGS = [
    {**SAMPLE_FINDING, "severity": "mineur", "line": 1, "problem": "Docstring absente"},
    {**SAMPLE_FINDING, "severity": "important", "line": 1, "problem": "Nom de fonction trop court"},
    SAMPLE_FINDING,
]

#: What a later hostile review finds.
LATER_FINDING = {**SAMPLE_FINDING, "problem": "Constat d'une revue plus récente"}

PREPARATION_FAILURE = 3
INCOMPLETE = 5
INVALID_OUTPUT = 6

NEW_FINDING = {
    **SAMPLE_FINDING,
    "severity": "important",
    "problem": "Le correctif renvoie une valeur au lieu de lever une erreur",
}


def rechecked(**statuses: str) -> Dict[str, Any]:
    """A re-review as the real Claude Code returns it, ruling `statuses` such as F1="traité"."""
    payload = success()
    structured = {
        "summary": "Les corrections tiennent en partie.",
        "statuses": {
            finding: {"status": status, "justification": f"Justification de {finding}."}
            for finding, status in statuses.items()
        },
        "findings": [NEW_FINDING],
    }
    payload["structured_output"] = structured
    payload["result"] = json.dumps(structured)
    return payload


class RecheckTest(FeatureBranchTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sb.fake.replies(success(findings=ORIGINAL_FINDINGS), rechecked(F1="traité", F2="mal traité"))

    def review(self, *options: str) -> Path:
        """Run a hostile review; returns its report."""
        review = self.sb.run("hostile-review", "main", *options)
        self.assertEqual(review.returncode, 0, review.stderr)
        return report_path(review.stdout)

    def review_then_fix(self, *options: str) -> Path:
        """Run a hostile review, then fix the code; returns the review's report."""
        report = self.review(*options)
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else FIXED_COMMITTED\n")
        self.sb.commit_all("fix")
        self.sb.write("nouveau.py", "FIXED_UNTRACKED = 1\n")
        return report

    def edit_companion(self, report: Path, **fields: Any) -> None:
        companion = report.with_suffix(".json")
        record = json.loads(companion.read_text(encoding="utf-8"))
        companion.write_text(json.dumps({**record, **fields}), encoding="utf-8")

    def assert_refused(self, args: Sequence[str], message: str) -> None:
        """The recheck stops before calling the reviewer, saying `message`."""
        calls = len(self.sb.fake.calls())

        result = self.sb.run("recheck", *args)

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(len(self.sb.fake.calls()), calls)

    def test_the_reviewer_rules_on_each_blocking_or_important_finding_and_reads_what_changed(self) -> None:
        self.review_then_fix()

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.sb.fake.last_call()
        stdin = call["stdin"]
        self.assertIn("Division par zéro non gérée", stdin)
        self.assertIn("Nom de fonction trop court", stdin)
        self.assertNotIn("Docstring absente", stdin)
        # The gap starts at the revision the original review read…
        self.assertIn("-    return a / b if b else 0", stdin)
        # …untracked files included, and the full diff starts at the merge-base.
        self.assertIn("+FIXED_UNTRACKED = 1", stdin)
        self.assertIn("-    return a / b\n", stdin)
        self.assertIn("--restricted", call["argv"])
        task = (PLUGIN / "prompts" / "recheck.md").read_text(encoding="utf-8")
        self.assertIn(task.splitlines()[0], call["system_prompt"] or "")
        schema = json.loads(option(call["argv"], "--json-schema"))
        self.assertEqual(schema["properties"]["statuses"]["required"], ["F1", "F2"])

    def test_the_report_rules_on_the_original_findings_and_numbers_new_ones_after_them(self) -> None:
        original = self.review_then_fix().stem

        result = self.sb.run("recheck")

        self.assertIn("# Re-revue\n", result.stdout)
        self.assertIn(f"| Rapport d'origine | {original} |", result.stdout)
        for ruling in [
            "### F1 · app.py:2 (bloquant) : traité\n\n"
            "- **Problème** : Division par zéro non gérée\n"
            "- **Justification** : Justification de F1.\n",
            "### F2 · app.py:1 (important) : mal traité\n\n"
            "- **Problème** : Nom de fonction trop court\n"
            "- **Justification** : Justification de F2.\n",
        ]:
            self.assertIn(ruling, result.stdout)
        self.assertIn("### F4 · app.py:2", result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual((companion["type"], companion["original"]), ("recheck", original))
        self.assertEqual(
            [(s["id"], s["problem"], s["status"], s["justification"]) for s in companion["statuses"]],
            [
                ("F1", "Division par zéro non gérée", "traité", "Justification de F1."),
                ("F2", "Nom de fonction trop court", "mal traité", "Justification de F2."),
            ],
        )
        self.assertEqual([finding["id"] for finding in companion["findings"]], ["F4"])

    def test_the_recheck_uses_the_model_of_the_original_review(self) -> None:
        self.review_then_fix("--model", "sonnet")

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(option(self.sb.fake.last_call()["argv"], "--model"), "sonnet")

    def test_a_report_designated_by_its_identifier_is_rechecked_rather_than_the_latest(self) -> None:
        self.sb.fake.replies(
            success(findings=ORIGINAL_FINDINGS),
            success(findings=[LATER_FINDING]),
            rechecked(F1="traité", F2="traité"),
        )
        original = self.review_then_fix().stem
        self.review()

        result = self.sb.run("recheck", original)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"| Rapport d'origine | {original} |", result.stdout)
        stdin = self.sb.fake.last_call()["stdin"]
        self.assertIn("Division par zéro non gérée", stdin)
        self.assertNotIn(LATER_FINDING["problem"], stdin)

    def test_a_report_designated_by_its_path_is_rechecked(self) -> None:
        report = self.review_then_fix()
        for designation in [report, report.with_suffix(".json")]:
            with self.subTest(designation=designation.name):
                result = self.sb.run("recheck", str(designation))

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"| Rapport d'origine | {report.stem} |", result.stdout)

    def test_rechecking_a_recheck_rules_on_what_it_left_open(self) -> None:
        self.sb.fake.replies(
            success(findings=ORIGINAL_FINDINGS),
            rechecked(F1="traité", F2="mal traité"),
            rechecked(F2="traité", F4="traité"),
        )
        self.review_then_fix()
        first = report_path(self.sb.run("recheck").stdout)
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else FIXED_AGAIN\n")

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"| Rapport d'origine | {first.stem} |", result.stdout)
        call = self.sb.fake.last_call()
        # F1 was fixed; F2 was badly fixed and the first recheck found F4.
        schema = json.loads(option(call["argv"], "--json-schema"))
        self.assertEqual(schema["properties"]["statuses"]["required"], ["F2", "F4"])
        self.assertNotIn("Division par zéro non gérée", call["stdin"])
        self.assertIn(NEW_FINDING["problem"], call["stdin"])
        self.assertIn("Dernier statut : mal traité. Justification de F2.", call["stdin"])
        # The gap starts at the revision the first recheck read.
        self.assertIn("-    return a / b if b else FIXED_COMMITTED", call["stdin"])
        self.assertNotIn("-    return a / b if b else 0", call["stdin"])
        self.assertIn("### F5 · app.py:2", result.stdout)

    def test_an_unknown_report_is_refused(self) -> None:
        self.review_then_fix()
        for designation in ["20200101T000000Z-hostile-000000", "inexistant.md", ".", "/", ".."]:
            with self.subTest(designation=designation):
                self.assert_refused([designation], "rapport introuvable")

    def test_a_repository_without_reports_has_nothing_to_recheck(self) -> None:
        self.assert_refused([], "aucun rapport")

    def test_a_report_of_another_repository_is_refused(self) -> None:
        report = self.review_then_fix()
        self.sb.git("remote", "add", "origin", "git@github.com:acme/autre.git")

        self.assert_refused([str(report)], "autre dépôt")

    def test_a_purged_original_revision_asks_for_a_full_review(self) -> None:
        report = self.review_then_fix()
        revision = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))["reviewed_revision"]
        (self.sb.repo / ".git" / "objects" / revision[:2] / revision[2:]).unlink()

        self.assert_refused([], "/delegate:hostile-review")

    def test_nothing_changed_since_the_review_leaves_nothing_to_recheck(self) -> None:
        self.review()

        self.assert_refused([], "aucun changement depuis le rapport d'origine")

    def test_fixes_that_undo_the_whole_change_are_still_ruled_on(self) -> None:
        self.review()
        self.sb.write("app.py", "def div(a, b):\n    return a / b\n")
        self.sb.commit_all("undo the change")

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-    return a / b if b else 0", self.sb.fake.last_call()["stdin"])

    def test_a_gap_and_a_full_diff_too_large_together_are_refused(self) -> None:
        self.review_then_fix()
        # About 700 000 characters in each diff: under the limit alone, over it together.
        self.sb.write("gros.py", "x = 1\n" * 100_000)

        self.assert_refused([], "diff trop volumineux")

    def test_a_failed_recheck_archives_nothing(self) -> None:
        report = self.review_then_fix()
        self.sb.fake.reply({**success(), "subtype": "error_max_budget_usd", "is_error": True}, 1)

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, INCOMPLETE, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(sorted(report.parent.glob("*.md")), [report])

    def test_a_malformed_report_is_refused(self) -> None:
        report = self.review_then_fix()
        self.edit_companion(report, reviewed_revision="--output=/tmp/x")

        self.assert_refused([], "rapport illisible")

    def test_a_pull_request_report_is_not_rechecked_yet(self) -> None:
        report = self.review_then_fix()
        self.edit_companion(report, type="pr")

        self.assert_refused([], "pull request")

    def test_a_recheck_that_skips_an_original_finding_is_an_invalid_output(self) -> None:
        self.sb.fake.replies(success(findings=ORIGINAL_FINDINGS), rechecked(F1="traité"))
        self.review_then_fix()

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, INVALID_OUTPUT, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_without_blocking_or_important_findings_only_what_changed_is_reviewed(self) -> None:
        self.sb.fake.replies(success(findings=[ORIGINAL_FINDINGS[0]]), rechecked())
        self.review_then_fix()

        result = self.sb.run("recheck")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Aucun constat bloquant ou important à vérifier.", result.stdout)
        self.assertIn("### F2 · app.py:2", result.stdout)
        schema = json.loads(option(self.sb.fake.last_call()["argv"], "--json-schema"))
        self.assertNotIn("required", schema["properties"]["statuses"])


if __name__ == "__main__":
    unittest.main()
