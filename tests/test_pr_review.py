from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import unittest
from typing import Any, Dict

from tests.support import (
    PLUGIN,
    SAMPLE_FINDING,
    PullRequestTestCase,
    interrupt_review,
    option,
    report_path,
    success,
)

PREPARATION_FAILURE = 3
USAGE_ERROR = 2
INVALID_OUTPUT = 6

REASON = "La division par zéro reste mal gérée."


def reviewed(verdict: Any = "REQUEST_CHANGES", reason: str = REASON) -> Dict[str, Any]:
    """A pull request review as the real Claude Code returns it."""
    payload = success()
    structured = {
        "summary": "La PR traite la division par zéro.",
        "verdict": verdict,
        "verdict_reason": reason,
        "findings": [SAMPLE_FINDING],
    }
    payload["structured_output"] = structured
    payload["result"] = json.dumps(structured)
    return payload


class PullRequestReviewTest(PullRequestTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sb.fake.reply(reviewed())

    def worktrees(self) -> int:
        return self.sb.git("worktree", "list", "--porcelain").count("worktree ")

    def test_the_reviewer_reads_the_pull_request_in_a_throwaway_worktree(self) -> None:
        status, head = self.sb.git("status", "--porcelain"), self.sb.git("rev-parse", "HEAD")

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.sb.fake.last_call()
        self.assertNotEqual(call["cwd"], str(self.sb.repo))
        self.assertIn("PR_CHANGE", call["cwd_files"]["app.py"])
        self.assertFalse(os.path.exists(call["cwd"]))
        self.assertEqual(self.worktrees(), 1)
        self.assertEqual(self.sb.git("status", "--porcelain"), status)
        self.assertEqual(self.sb.git("rev-parse", "HEAD"), head)

    def test_the_pull_request_and_its_diff_since_the_target_branch_reach_the_reviewer(self) -> None:
        self.sb.write("later.py", "LATER_ON_MAIN = 1\n")
        self.sb.commit_all("main moves on")
        self.sb.git("push", "-q", "origin", "main")

        self.run_pr()

        stdin = self.sb.fake.last_call()["stdin"]
        for text in [
            "Gérer la division par zéro",
            "Cette PR renvoie PR_CHANGE quand b vaut zéro.",
            "https://github.com/acme/app/pull/7",
            self.head,
            "+    return a / b if b else PR_CHANGE",
        ]:
            self.assertIn(text, stdin)
        self.assertNotIn("LATER_ON_MAIN", stdin)
        self.assertIn(
            ["pr", "view", "7", "--repo", "github.com/acme/app", "--json", "title,body,baseRefName,headRefOid,url"],
            self.gh.calls(),
        )

    def test_the_review_moves_no_ref_of_the_repository(self) -> None:
        self.move_target_branch({"later.py": "LATER_ON_MAIN = 1\n"})
        refs = self.sb.git("for-each-ref")

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sb.git("for-each-ref"), refs)

    def test_the_pull_request_configuration_never_reaches_the_reviewer(self) -> None:
        self.update_pull_request(
            {
                "CLAUDE.md": "INSTRUCTION_DE_LA_PR\n",
                "CLAUDE.local.md": "local\n",
                "sub/CLAUDE.md": "imbrique\n",
                "sub/.claude/settings.json": "{}\n",
                ".mcp.json": "{}\n",
                # Same files on a case-insensitive file system, as on macOS.
                "docs/claude.md": "minuscules\n",
                ".Claude/agents/espion.md": "agent\n",
            }
        )

        self.run_pr()

        call = self.sb.fake.last_call()
        for path in [
            "CLAUDE.md",
            "CLAUDE.local.md",
            "sub/CLAUDE.md",
            "sub/.claude/settings.json",
            ".mcp.json",
            "docs/claude.md",
            ".Claude/agents/espion.md",
        ]:
            self.assertNotIn(path, call["cwd_files"])
        self.assertIn("app.py", call["cwd_files"])
        self.assertNotIn("INSTRUCTION_DE_LA_PR", call["system_prompt"] or "")

    def test_changed_files_the_reviewer_cannot_read_are_named_for_a_human(self) -> None:
        self.update_pull_request(
            {
                "app.py": "def div(a, b):\n    return a / b if b else PR_CHANGE\n",
                ".claude/settings.json": '{"hooks": "HOOK_DE_LA_PR"}\n',
                "config/.env.local": "SECRET_DE_LA_PR=1\n",
            }
        )

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        stdin = self.sb.fake.last_call()["stdin"]
        self.assertIn("Fichiers non relus : .claude/settings.json, config/.env.local", stdin)
        self.assertNotIn("HOOK_DE_LA_PR", stdin)
        self.assertNotIn("SECRET_DE_LA_PR", stdin)
        self.assertIn("| Fichiers non relus | .claude/settings.json, config/.env.local |", result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(companion["unreviewed_files"], [".claude/settings.json", "config/.env.local"])

    def test_a_pull_request_changing_only_files_the_reviewer_cannot_read_is_not_called_empty(self) -> None:
        self.update_pull_request({".claude/settings.json": '{"hooks": "HOOK_DE_LA_PR"}\n'})

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn(".claude/settings.json", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_no_git_hook_runs_on_the_pull_request_checkout(self) -> None:
        """A post-checkout hook runs inside the new worktree, where it could run
        the pull request's own code (npm install, lefthook…)."""
        witness = self.sb.root / "hook-ran"
        hook = self.sb.root / "hooks" / "post-checkout"
        hook.parent.mkdir()
        hook.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(witness))}\n", encoding="utf-8")
        hook.chmod(0o755)
        self.sb.git("config", "core.hooksPath", str(hook.parent))

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(witness.exists())

    def test_conventions_come_from_the_target_branch_never_from_the_pull_request(self) -> None:
        self.sb.write("CLAUDE.md", "CONVENTION_CIBLE\n")
        self.sb.commit_all("conventions")
        self.sb.git("push", "-q", "origin", "main")
        self.update_pull_request({"CLAUDE.md": "CONVENTION_DE_LA_PR\n"})

        self.run_pr()

        prompt = self.sb.fake.last_call()["system_prompt"] or ""
        self.assertIn((PLUGIN / "prompts" / "pr-review.md").read_text(encoding="utf-8").strip(), prompt)
        self.assertIn("CONVENTION_CIBLE", prompt)
        self.assertNotIn("CONVENTION_DE_LA_PR", prompt)

    def test_unreadable_conventions_of_the_target_branch_stop_the_review(self) -> None:
        self.sb.write("CLAUDE.md", "CONVENTION_CIBLE\n")
        self.sb.commit_all("conventions")
        self.sb.git("push", "-q", "origin", "main")
        self.update_pull_request({"app.py": "def div(a, b):\n    return a / b if b else PR_CHANGE\n"})
        blob = self.sb.git("rev-parse", "main:CLAUDE.md")
        (self.sb.repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        target = self.sb.git("rev-parse", "main")
        self.assertIn(f"conventions illisibles : CLAUDE.md à la révision {target[:12]}", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_the_report_gives_the_verdict_and_identifies_the_pull_request(self) -> None:
        result = self.run_pr()

        self.assertIn(f"## Verdict\n\nREQUEST_CHANGES : {REASON}", result.stdout)
        self.assertIn("| Pull request | #7 https://github.com/acme/app/pull/7 |", result.stdout)
        self.assertIn("| Branche cible | main |", result.stdout)
        self.assertIn(f"| Tête | {self.head} |", result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(
            (companion["type"], companion["head"], companion["verdict"]), ("pr", self.head, "REQUEST_CHANGES")
        )
        schema = json.loads(option(self.sb.fake.last_call()["argv"], "--json-schema"))
        self.assertEqual(schema["properties"]["verdict"]["enum"], ["APPROVE", "REQUEST_CHANGES"])

    def test_a_review_without_a_valid_verdict_is_an_invalid_output(self) -> None:
        for verdict in [None, "MAYBE"]:
            with self.subTest(verdict=verdict):
                self.sb.fake.reply(reviewed(verdict=verdict))

                result = self.run_pr()

                self.assertEqual(result.returncode, INVALID_OUTPUT, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_the_worktree_is_removed_when_the_review_fails(self) -> None:
        self.sb.fake.reply({**success(), "is_error": True, "result": "boom"}, 1)

        result = self.run_pr()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(self.sb.fake.last_call()["cwd"]))
        self.assertEqual(self.worktrees(), 1)

    def test_an_interrupted_review_removes_the_worktree(self) -> None:
        self.sb.fake.reply(reviewed(), sleep=30)

        call, _ = interrupt_review(self.sb, ["pr-review", self.NUMBER], signal.SIGINT, {"PATH": self.path_with_gh()})

        self.assertFalse(os.path.exists(call["cwd"]))
        self.assertEqual(self.worktrees(), 1)

    def test_a_force_pushed_pull_request_can_be_reviewed_again(self) -> None:
        self.run_pr()
        self.update_pull_request({"app.py": "AFTER_FORCE_PUSH = 1\n"})

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AFTER_FORCE_PUSH", self.sb.fake.last_call()["stdin"])

    def test_invalid_pull_request_numbers_are_refused(self) -> None:
        for number in ["7a", "-1", "../7", "0"]:
            with self.subTest(number):
                self.assertEqual(self.sb.run("pr-review", number).returncode, USAGE_ERROR)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_an_origin_that_is_not_on_github_is_refused(self) -> None:
        self.sb.git("remote", "set-url", "origin", str(self.origin))

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("forge", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_a_pull_request_that_moves_during_preparation_is_not_reviewed(self) -> None:
        self.gh.reply(self.metadata(headRefOid="0" * 40))

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("relance", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_without_gh_the_review_says_where_to_get_it(self) -> None:
        only_git = self.sb.root / "only-git"
        only_git.mkdir()
        git = shutil.which("git")
        assert git is not None
        (only_git / "git").symlink_to(git)

        result = self.sb.run("pr-review", self.NUMBER, extra_env={"PATH": str(only_git)})

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("https://cli.github.com", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_a_pull_request_gh_cannot_read_is_a_preparation_failure(self) -> None:
        self.gh.fail("GraphQL: Could not resolve to a PullRequest with the number of 7.")

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("Could not resolve to a PullRequest", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])


if __name__ == "__main__":
    unittest.main()
