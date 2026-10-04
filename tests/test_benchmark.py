"""The benchmark of the reviewer models, run as a process in `--dry-run`: it
must build a repository per case, go through the plugin's own review and score
the report, without calling any model."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import ROOT

sys.path.insert(0, str(ROOT))
from benchmark.compare import Planted, split  # noqa: E402

BENCHMARK = ROOT / "benchmark" / "compare.py"
CASES = ROOT / "benchmark" / "cases"


class BenchmarkTest(unittest.TestCase):
    """The whole measurement runs offline and costs nothing, once the reviewer
    is faked: a dry run is the only shape a test can afford."""

    def dry_run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BENCHMARK), "--dry-run", *arguments],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_every_case_is_reviewed_by_every_model_and_scored(self) -> None:
        done = self.dry_run("--models", "opus", "fable")

        self.assertEqual(done.returncode, 0, done.stderr)
        for model in ("opus", "fable"):
            for case in ("divide", "pagination", "rounding", "cache", "counter", "clean", "tidy"):
                self.assertIn(f"| {model} | {case} |", done.stdout, done.stdout)

    def test_a_planted_defect_the_answer_names_is_counted_as_found(self) -> None:
        # The fake finds every planted defect, and reports one finding on
        # divide that matches none of them.
        done = self.dry_run(
            "--models", "opus",
            "--cases", "divide", "pagination", "rounding", "cache", "counter",
        )

        self.assertEqual(done.returncode, 0, done.stderr)
        for case in ("divide", "rounding", "cache", "counter"):
            self.assertIn(f"| opus | {case} | 1/1 |", done.stdout)
        self.assertIn("| opus | pagination | 2/2 |", done.stdout)
        self.assertIn("| opus | 6 | 0 | 1 |", done.stdout)

    def test_a_finding_matching_no_planted_defect_is_reported_as_invented(self) -> None:
        done = self.dry_run("--models", "opus", "--cases", "divide")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1 constat(s) inventé(s)", done.stdout)
        self.assertIn("Constat qui ne correspond à aucun défaut planté", done.stdout)

    def test_the_audit_of_a_case_is_printed_with_what_it_invented(self) -> None:
        # An invented finding is only triageable against the reading of the
        # case, so the note travels with it rather than sitting in the file.
        done = self.dry_run("--models", "opus", "--cases", "divide")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Cas audité le 2026-10-04", done.stdout)
        self.assertIn("| divide | 2026-10-04 |", done.stdout)

    def test_a_clean_case_scores_precision_alone(self) -> None:
        # No defect is planted, so any finding at all is invented: the fake
        # answers none, and the case must not look like a recall of zero.
        done = self.dry_run("--models", "opus", "--cases", "clean", "tidy")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("| opus | clean | 0/0 | 0 |", done.stdout)
        self.assertIn("| opus | tidy | 0/0 | 0 |", done.stdout)

    def test_the_run_says_it_called_no_model(self) -> None:
        done = self.dry_run("--models", "opus", "--cases", "clean")

        self.assertIn("aucun appel au modèle", done.stdout)

    def test_an_unknown_case_is_refused_before_any_review(self) -> None:
        done = self.dry_run("--models", "opus", "--cases", "inexistant")

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("inexistant", done.stderr)

    def test_every_case_holds_what_the_scoring_needs(self) -> None:
        # A case without its two revisions, or whose planted defects name
        # another file, would only fail during a real, paid run.
        for directory in sorted(path for path in CASES.iterdir() if path.is_dir()):
            with self.subTest(case=directory.name):
                specification = json.loads((directory / "case.json").read_text(encoding="utf-8"))
                self.assertTrue(specification["title"])
                self.assertTrue(specification["why"])
                self.assertTrue((directory / "before").is_dir())
                self.assertTrue((directory / "after").is_dir())
                touched = {
                    path.relative_to(directory / "after")
                    for path in (directory / "after").rglob("*")
                    if path.is_file()
                }
                for defect in specification["planted"]:
                    self.assertIn(defect["file"], {str(path) for path in touched})
                    self.assertTrue(defect.get("keywords") or defect.get("facets"))
                    self.assertIn(defect["severity"], ("bloquant", "important", "mineur"))
                # A case nobody has read is a case whose "invented" findings
                # cannot be told from real defects. The audit is what makes a
                # score mean something, so its absence fails the suite.
                trusted = specification["trusted"]
                self.assertTrue(trusted["audited_on"])
                self.assertTrue(trusted["note"])


class ScoringTest(unittest.TestCase):
    """The split between planted defects and invented findings, as a pure
    function: coupled defects are the part worth pinning down."""

    PLANTED = [
        Planted(
            id="coupled",
            severity="important",
            file="paging.py",
            line=16,
            problem="Two parts",
            facets=[["size", "taille"], ["last_page_number", "borne"]],
        )
    ]

    def finding(self, text: str, file: str = "paging.py") -> dict:
        return {"file": file, "line": 16, "problem": text, "failure_scenario": "", "fix": ""}

    def test_both_parts_across_two_findings_are_found(self) -> None:
        found, missed, invented = split(
            [
                self.finding("Le paramètre size n'est plus transmis"),
                self.finding("last_page_number est faux"),
            ],
            self.PLANTED,
        )

        self.assertEqual(found, ["coupled"])
        self.assertEqual(missed, [])
        self.assertEqual(invented, [])

    def test_one_part_alone_misses_the_defect_without_inventing_a_finding(self) -> None:
        # The finding is explained, because it names a part, but the defect is
        # not found: half of a coupled fix is not the fix.
        found, missed, invented = split(
            [self.finding("Le paramètre size n'est plus transmis")], self.PLANTED
        )

        self.assertEqual(found, [])
        self.assertEqual(missed, ["coupled"])
        self.assertEqual(invented, [])

    def test_both_parts_in_one_finding_are_found(self) -> None:
        found, missed, invented = split(
            [self.finding("size n'est pas transmis à last_page_number")], self.PLANTED
        )

        self.assertEqual(found, ["coupled"])
        self.assertEqual(invented, [])

    def test_a_finding_naming_a_part_on_another_file_is_invented(self) -> None:
        finding = self.finding("size et last_page_number", file="autre.py")

        found, missed, invented = split([finding], self.PLANTED)

        self.assertEqual(found, [])
        self.assertEqual(missed, ["coupled"])
        self.assertEqual(invented, [finding])


if __name__ == "__main__":
    unittest.main()
