from __future__ import annotations

import json
import os
import unittest
from typing import List

from tests.support import MergeRequestTestCase, pr_review_result, report_path

PREPARATION_FAILURE = 3
USAGE_ERROR = 2


def api_call(host: str, project: str) -> List[str]:
    return ["api", "--hostname", host, f"projects/{project}/merge_requests/7"]


class MergeRequestReviewTest(MergeRequestTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.sb.fake.reply(pr_review_result())

    def test_a_gitlab_merge_request_is_reviewed_on_its_own_code(self) -> None:
        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        # A single read from GitLab: nothing is published there.
        self.assertEqual(self.forge_cli.calls(), [api_call("gitlab.example.com", "acme%2Fapp")])
        call = self.sb.fake.last_call()
        self.assertIn("PR_CHANGE", call["cwd_files"]["app.py"])
        self.assertFalse(os.path.exists(call["cwd"]))
        for text in [
            "Merge request !7 : Gérer la division par zéro",
            "Cette MR renvoie PR_CHANGE quand b vaut zéro.",
            self.head,
            "+    return a / b if b else PR_CHANGE",
        ]:
            self.assertIn(text, call["stdin"])
        self.assertIn("# Revue de merge request\n", result.stdout)
        self.assertIn("| Merge request | !7 https://gitlab.example.com/acme/app/-/merge_requests/7 |", result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual((companion["type"], companion["forge"]), ("pr", "gitlab"))

    def test_the_merge_request_configuration_never_reaches_the_reviewer(self) -> None:
        self.sb.write("CLAUDE.md", "CONVENTION_CIBLE\n")
        self.sb.commit_all("conventions")
        self.sb.git("push", "-q", "origin", "main")
        self.update_pull_request(
            {"CLAUDE.md": "INSTRUCTION_DE_LA_MR\n", ".claude/agents/espion.md": "agent\n", ".mcp.json": "{}\n"}
        )

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        call = self.sb.fake.last_call()
        for path in ["CLAUDE.md", ".claude/agents/espion.md", ".mcp.json"]:
            self.assertNotIn(path, call["cwd_files"])
        self.assertIn("CONVENTION_CIBLE", call["system_prompt"] or "")
        self.assertNotIn("INSTRUCTION_DE_LA_MR", call["system_prompt"] or "")
        self.assertEqual(self.sb.git("worktree", "list", "--porcelain").count("worktree "), 1)

    def test_a_project_in_nested_groups_is_found(self) -> None:
        self.use_origin("https://gitlab.example.com/acme/outils/app.git")

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.forge_cli.calls(), [api_call("gitlab.example.com", "acme%2Foutils%2Fapp")])

    def test_a_host_known_to_glab_is_taken_for_gitlab(self) -> None:
        self.use_origin("https://ci.example.com/acme/app.git")

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.forge_cli.calls(),
            [["auth", "status", "--hostname", "ci.example.com"], api_call("ci.example.com", "acme%2Fapp")],
        )

    def test_a_host_no_forge_claims_asks_for_the_forge_option(self) -> None:
        self.use_origin("https://git.example.com/acme/app.git")
        self.forge_cli.fail("git.example.com: not authenticated")

        result = self.run_pr()

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("--forge", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_the_forge_option_forces_gitlab(self) -> None:
        self.use_origin("https://git.example.com/acme/app.git")

        result = self.run_pr("--forge", "gitlab")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.forge_cli.calls(), [api_call("git.example.com", "acme%2Fapp")])

    def test_only_known_forges_can_be_forced(self) -> None:
        self.assertEqual(self.run_pr("--forge", "bitbucket").returncode, USAGE_ERROR)

    def test_a_merge_request_without_description_is_reviewed(self) -> None:
        self.forge_cli.reply(self.metadata(description=None))

        result = self.run_pr()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(aucune description)", self.sb.fake.last_call()["stdin"])

    def test_without_glab_the_review_says_where_to_get_it(self) -> None:
        result = self.sb.run("pr-review", self.NUMBER, extra_env={"PATH": self.path_with_only_git()})

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("https://gitlab.com/gitlab-org/cli", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])

    def test_without_glab_a_host_only_glab_would_know_is_explained(self) -> None:
        self.use_origin("https://ci.example.com/acme/app.git")

        result = self.sb.run("pr-review", self.NUMBER, extra_env={"PATH": self.path_with_only_git()})

        self.assertEqual(result.returncode, PREPARATION_FAILURE, result.stderr)
        self.assertIn("--forge", result.stderr)
        self.assertIn("https://gitlab.com/gitlab-org/cli", result.stderr)
        self.assertEqual(self.sb.fake.calls(), [])


if __name__ == "__main__":
    unittest.main()
