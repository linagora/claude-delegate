from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.support import FeatureBranchTestCase



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

    def test_the_users_index_is_left_untouched(self) -> None:
        self.sb.write("staged.py", "STAGED = 1\n")
        self.sb.git("add", "staged.py")
        self.sb.write("staged.py", "STAGED = 2\n")
        self.sb.write("new_module.py", "UNTRACKED_CHANGE = 1\n")
        index = self.sb.repo / ".git" / "index"
        before = index.read_bytes()

        self.sb.run("hostile-review", "main")

        self.assertEqual(index.read_bytes(), before)

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


if __name__ == "__main__":
    unittest.main()
