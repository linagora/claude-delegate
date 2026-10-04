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
        done = self.dry_run("--models", "opus", "fable", "--cases", "divide", "pagination", "clean")

        self.assertEqual(done.returncode, 0, done.stderr)
        for model in ("opus", "fable"):
            for case in ("divide", "pagination", "clean"):
                self.assertIn(f"| {model} | {case} |", done.stdout, done.stdout)

    def test_a_planted_defect_the_answer_names_is_counted_as_found(self) -> None:
        # The fake finds the zero division and the lost last chunk: the two
        # planted defects are found, and nothing is reported as missed.
        done = self.dry_run("--models", "opus", "--cases", "divide", "pagination")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("| opus | divide | 1/1 |", done.stdout)
        self.assertIn("| opus | pagination | 1/1 |", done.stdout)
        self.assertIn("| opus | 2 | 0 | 1 |", done.stdout)

    def test_a_finding_matching_no_planted_defect_is_reported_as_invented(self) -> None:
        done = self.dry_run("--models", "opus", "--cases", "divide")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1 constat(s) inventé(s)", done.stdout)
        self.assertIn("Constat qui ne correspond à aucun défaut planté", done.stdout)

    def test_a_clean_case_scores_precision_alone(self) -> None:
        # No defect is planted, so any finding at all is invented: the fake
        # answers none, and the case must not look like a recall of zero.
        done = self.dry_run("--models", "opus", "--cases", "clean")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("| opus | clean | 0/0 | 0 |", done.stdout)

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
                    self.assertTrue(defect["keywords"])
                    self.assertIn(defect["severity"], ("bloquant", "important", "mineur"))


if __name__ == "__main__":
    unittest.main()
