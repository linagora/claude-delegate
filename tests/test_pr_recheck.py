from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from tests.support import (
    MergeRequestTestCase,
    PullRequestTestCase,
    option,
    pr_review_result,
    recheck_result,
    report_path,
    rewrite_companion,
    success,
)

PREPARATION_FAILURE = 3

FIXED = "def div(a, b):\n    if not b:\n        raise ValueError(PR_FIX)\n    return a / b\n"


class PullRequestRecheckTest(PullRequestTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sb.fake.replies(pr_review_result(), recheck_result(F1="traité"))

    def review(self, *options: str) -> Path:
        result = self.run_pr(*options)
        self.assertEqual(result.returncode, 0, result.stderr)
        return report_path(result.stdout)

    def test_the_new_head_is_rechecked_in_a_throwaway_worktree(self) -> None:
        original = self.review()
        self.extend_pull_request({"app.py": FIXED})
        status, head = self.sb.git("status", "--porcelain"), self.sb.git("rev-parse", "HEAD")

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.sb.fake.last_call()
        self.assertIn("PR_FIX", call["cwd_files"]["app.py"])
        self.assertFalse(os.path.exists(call["cwd"]))
        self.assertEqual(self.worktrees(), 1)
        self.assertEqual((self.sb.git("status", "--porcelain"), self.sb.git("rev-parse", "HEAD")), (status, head))
        # The finding to rule on, then the gap from the head the review read.
        self.assertIn("Division par zéro non gérée", call["stdin"])
        self.assertIn("-    return a / b if b else PR_CHANGE", call["stdin"])
        self.assertIn("+        raise ValueError(PR_FIX)", call["stdin"])
        self.assertEqual(self.forge_cli.calls()[-1][:3], ["pr", "view", "7"])
        self.assertIn(f"| Rapport d'origine | {original.stem} |", result.stdout)
        self.assertIn("| Pull request | #7 https://github.com/acme/app/pull/7 |", result.stdout)
        self.assertIn(f"| Tête | {self.head} |", result.stdout)

    def test_the_recheck_never_sees_the_pull_request_configuration(self) -> None:
        self.sb.write("CLAUDE.md", "CONVENTION_CIBLE\n")
        self.sb.commit_all("conventions")
        self.sb.git("push", "-q", "origin", "main")
        self.review()
        self.extend_pull_request({"app.py": FIXED, "CLAUDE.md": "INSTRUCTION_DE_LA_PR\n", ".mcp.json": "{}\n"})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.sb.fake.last_call()
        for path in ["CLAUDE.md", ".mcp.json"]:
            self.assertNotIn(path, call["cwd_files"])
        prompt = call["system_prompt"] or ""
        self.assertIn("CONVENTION_CIBLE", prompt)
        self.assertNotIn("INSTRUCTION_DE_LA_PR", prompt)
        self.assertIn("CLAUDE.local.md", prompt)

    def test_changed_files_the_reviewer_cannot_read_are_named_again(self) -> None:
        self.review()
        self.extend_pull_request({"app.py": FIXED, ".env.local": "SECRET_DE_LA_PR=1\n"})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fichiers non relus : .env.local", self.sb.fake.last_call()["stdin"])
        self.assertNotIn("SECRET_DE_LA_PR", self.sb.fake.last_call()["stdin"])
        self.assertIn("| Fichiers non relus | .env.local |", result.stdout)

    def test_the_recheck_uses_the_model_of_the_review(self) -> None:
        self.review("--model", "sonnet")
        self.extend_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(option(self.sb.fake.last_call()["argv"], "--model"), "sonnet")

    def test_the_worktree_is_removed_when_the_recheck_fails(self) -> None:
        self.sb.fake.replies(pr_review_result(), {**success(), "is_error": True, "result": "boom"})
        self.review()
        self.extend_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(self.sb.fake.last_call()["cwd"]))
        self.assertEqual(self.worktrees(), 1)

    def test_a_force_pushed_pull_request_is_rechecked_from_its_old_head(self) -> None:
        self.review()
        self.update_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        stdin = self.sb.fake.last_call()["stdin"]
        self.assertIn("-    return a / b if b else PR_CHANGE", stdin)
        self.assertIn("+        raise ValueError(PR_FIX)", stdin)

    def test_an_old_head_purged_after_a_force_push_asks_for_a_full_review(self) -> None:
        self.review()
        old_head = self.head
        self.update_pull_request({"app.py": FIXED})
        (self.sb.repo / ".git" / "objects" / old_head[:2] / old_head[2:]).unlink()

        result = self.run_recheck()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("/delegate:pr-review 7 --forge github", result.stderr)
        self.assertEqual(len(self.sb.fake.calls()), 1)

    def test_a_pull_request_unchanged_since_the_review_has_nothing_to_recheck(self) -> None:
        self.review()

        result = self.run_recheck()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("aucun changement depuis le rapport d'origine", result.stderr)

    def test_a_review_recorded_before_gitlab_support_is_rechecked_on_github(self) -> None:
        original = self.review()
        record = json.loads(original.with_suffix(".json").read_text(encoding="utf-8"))
        del record["forge"]
        original.with_suffix(".json").write_text(json.dumps(record), encoding="utf-8")
        self.extend_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.forge_cli.calls()[-1][:3], ["pr", "view", "7"])

    def test_a_review_naming_its_forge_badly_is_refused(self) -> None:
        original = self.review()
        rewrite_companion(original, forge=["github"])
        self.extend_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("rapport illisible", result.stderr)

    def test_rechecking_a_pull_request_recheck_follows_its_new_head(self) -> None:
        self.sb.fake.replies(
            pr_review_result(), recheck_result(F1="mal traité"), recheck_result(F1="traité", F2="traité")
        )
        self.review()
        self.extend_pull_request({"app.py": FIXED})
        first = report_path(self.run_recheck().stdout)
        self.extend_pull_request({"autre.py": "SECOND_FIX = 1\n"})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"| Rapport d'origine | {first.stem} |", result.stdout)
        self.assertIn(f"| Tête | {self.head} |", result.stdout)
        call = self.sb.fake.last_call()
        # F1 was badly fixed, and the first recheck found F2.
        schema = json.loads(option(call["argv"], "--json-schema"))
        self.assertEqual(schema["properties"]["statuses"]["required"], ["F1", "F2"])
        gap = call["stdin"].split("--- Début de l'écart", 1)[1].split("--- Fin de l'écart", 1)[0]
        self.assertIn("+SECOND_FIX = 1", gap)
        self.assertNotIn("PR_FIX", gap)


class MergeRequestRecheckTest(MergeRequestTestCase):
    def test_a_merge_request_is_rechecked_through_glab(self) -> None:
        self.sb.fake.replies(pr_review_result(), recheck_result(F1="traité"))
        self.assertEqual(self.run_pr().returncode, 0)
        self.extend_pull_request({"app.py": FIXED})

        result = self.run_recheck()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.forge_cli.calls()[-1][:3], ["api", "--hostname", "gitlab.example.com"])
        self.assertIn("PR_FIX", self.sb.fake.last_call()["cwd_files"]["app.py"])
        self.assertIn("| Merge request | !7 https://gitlab.example.com/acme/app/-/merge_requests/7 |", result.stdout)


if __name__ == "__main__":
    unittest.main()
