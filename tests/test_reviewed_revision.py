from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path

from tests.support import FeatureBranchTestCase

PREPARATION_FAILURE = 3


class ReviewedRevisionTest(FeatureBranchTestCase):
    def test_untracked_files_are_reviewed_but_ignored_ones_are_not(self) -> None:
        self.sb.write(".gitignore", "*.log\n")
        self.sb.commit_all("ignore logs")
        self.sb.write("new_module.py", "UNTRACKED_CHANGE = 1\n")
        self.sb.write("debug.log", "IGNORED_CONTENT\n")

        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        reviewed = self.sb.fake.last_call()["stdin"]
        self.assertIn("UNTRACKED_CHANGE", reviewed)
        self.assertNotIn("IGNORED_CONTENT", reviewed)

    def test_a_file_that_is_not_utf8_is_reviewed_without_crashing(self) -> None:
        (self.sb.repo / "latin1.txt").write_bytes("prix = 'café'\n".encode("latin-1"))

        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prix = 'caf", self.sb.fake.last_call()["stdin"])

    def test_the_users_index_is_left_untouched(self) -> None:
        self.sb.write("staged.py", "STAGED = 1\n")
        self.sb.git("add", "staged.py")
        self.sb.write("staged.py", "STAGED = 2\n")
        self.sb.write("new_module.py", "UNTRACKED_CHANGE = 1\n")
        index = self.sb.repo / ".git" / "index"
        before = index.read_bytes()

        self.sb.run("hostile-review", "main")

        self.assertEqual(index.read_bytes(), before)

    def test_a_file_rewritten_right_after_staging_is_reviewed_as_rewritten(self) -> None:
        # Same size, same mtime, ctime ignored: only git's racy-entry check,
        # which compares entries with the index timestamp, can see the change.
        self.sb.git("config", "core.trustctime", "false")
        staged = self.sb.repo / "staged.py"
        past = time.time() - 100
        self.sb.write("staged.py", "STAGED = 1\n")
        os.utime(staged, (past, past))
        self.sb.git("add", "staged.py")
        os.utime(self.sb.repo / ".git" / "index", (past, past))
        self.sb.write("staged.py", "STAGED = 2\n")
        os.utime(staged, (past, past))

        self.sb.run("hostile-review", "main")

        self.assertIn("+STAGED = 2", self.sb.fake.last_call()["stdin"])

    def test_the_reviewed_revision_is_an_unreferenced_commit_on_top_of_head(self) -> None:
        self.sb.write("new_module.py", "UNTRACKED_CHANGE = 1\n")
        head = self.sb.git("rev-parse", "HEAD")

        result = self.sb.run("hostile-review", "main")

        report = Path(result.stdout.partition("\n")[0][len("Rapport : ") :])
        snapshot = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))["snapshot"]
        self.assertIn(f"| Révision relue | {snapshot[:12]} |", result.stdout)
        self.assertEqual(self.sb.git("rev-parse", f"{snapshot}^"), head)
        self.assertEqual(self.sb.git("show", f"{snapshot}:new_module.py"), "UNTRACKED_CHANGE = 1")
        self.assertEqual(self.sb.git("for-each-ref", "--contains", snapshot), "")
        self.assertEqual(self.sb.git("rev-parse", "HEAD"), head)

    def test_an_unknown_base_fails_without_calling_the_reviewer(self) -> None:
        result = self.sb.run("hostile-review", "no-such-branch")

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("base introuvable : no-such-branch", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_nothing_to_review_fails_without_calling_the_reviewer(self) -> None:
        self.sb.git("switch", "-q", "main")

        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("rien à relire", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])


if __name__ == "__main__":
    unittest.main()
