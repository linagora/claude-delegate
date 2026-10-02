from __future__ import annotations

import hashlib
import json
import re
import unittest

from tests.support import PLUGIN, SAMPLE_FINDING, FeatureBranchTestCase, option, report_path, success


def section(report: str, title: str) -> str:
    """The body of a `## title` section of a Markdown report."""
    body = report.split(f"\n## {title}\n", 1)[1]
    return body.split("\n## ", 1)[0].strip()


class HostileReviewTest(FeatureBranchTestCase):
    def test_review_reports_the_delegate_findings(self) -> None:
        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Division par zéro non gérée", result.stdout)

    def test_reviewer_reads_changes_since_the_merge_base_including_uncommitted_ones(self) -> None:
        self.sb.git("switch", "-q", "main")
        self.sb.write("drift.py", "DRIFT_ON_MAIN = 1\n")
        self.sb.commit_all("main moves on")
        self.sb.git("switch", "-q", "feature")
        self.sb.write("staged.py", "STAGED_CHANGE = 1\n")
        self.sb.git("add", "staged.py")
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else UNSTAGED_CHANGE\n")

        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        reviewed = self.sb.fake.last_call()["stdin"]
        self.assertIn("STAGED_CHANGE", reviewed)
        self.assertIn("UNSTAGED_CHANGE", reviewed)
        self.assertNotIn("DRIFT_ON_MAIN", reviewed)

    def test_reviewer_is_read_only_and_ignores_project_configuration(self) -> None:
        self.sb.run("hostile-review", "main")

        argv = self.sb.fake.last_call()["argv"]
        self.assertIn("-p", argv)
        self.assertIn("--restricted", argv)
        self.assertEqual(option(argv, "--tools"), "Read,Grep,Glob")
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(option(argv, "--permission-mode"), "dontAsk")
        self.assertIn("--no-session-persistence", argv)
        deny = json.loads(option(argv, "--settings"))["permissions"]["deny"]
        self.assertEqual(
            set(deny), {"Read(**/.env)", "Read(**/.env.*)", "Read(**/.claude/settings*.json)"}
        )

    def test_reviewer_is_opus_with_bounded_turns_and_budget(self) -> None:
        self.sb.run("hostile-review", "main")

        argv = self.sb.fake.last_call()["argv"]
        self.assertEqual(option(argv, "--model"), "opus")
        self.assertEqual(option(argv, "--effort"), "high")
        self.assertEqual(option(argv, "--max-turns"), "30")
        self.assertEqual(option(argv, "--max-budget-usd"), "5")

    def test_reviewer_must_answer_with_the_findings_schema(self) -> None:
        self.sb.run("hostile-review", "main")

        argv = self.sb.fake.last_call()["argv"]
        self.assertEqual(option(argv, "--output-format"), "json")
        schema = json.loads(option(argv, "--json-schema"))
        finding = schema["properties"]["findings"]["items"]
        self.assertEqual(set(schema["required"]), {"summary", "findings"})
        self.assertEqual(finding["properties"]["severity"]["enum"], ["bloquant", "important", "mineur"])
        self.assertEqual(
            set(finding["required"]),
            {"severity", "file", "line", "problem", "failure_scenario", "fix"},
        )

    def test_reviewer_gets_the_hostile_prompt_and_works_from_the_repository_root(self) -> None:
        (self.sb.repo / "pkg").mkdir()

        self.sb.run("hostile-review", "main", cwd=self.sb.repo / "pkg")

        call = self.sb.fake.last_call()
        self.assertEqual(call["cwd"], str(self.sb.repo))
        self.assertIn("Pars du principe que le code est faux", call["system_prompt"] or "")

    def test_reviewer_environment_is_rebuilt_from_scratch(self) -> None:
        session_env = {
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "sk-deepseek",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-flash",
            "CLAUDE_CODE_EFFORT_LEVEL": "low",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "LITELLM_API_KEY": "sk-litellm",
            "GH_TOKEN": "ghp_secret",
            "USER": "alice",
            "LOGNAME": "alice",
            "LANG": "fr_FR.UTF-8",
            "LC_ALL": "fr_FR.UTF-8",
            "TERM": "xterm-256color",
            "TMPDIR": "/tmp/alice",
        }

        self.sb.run("hostile-review", "main", extra_env=session_env)

        env = self.sb.fake.last_call()["env"]
        self.assertEqual(env.get("CLAUDE_CONFIG_DIR"), str(self.sb.home / ".claude-anthropic"))
        added_by_the_os = {"__CF_USER_TEXT_ENCODING"}  # macOS sets it in every process
        self.assertEqual(
            set(env) - {"CLAUDE_CONFIG_DIR"} - added_by_the_os,
            {"HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR"},
        )

    def test_findings_are_numbered_by_severity_and_empty_sections_say_so(self) -> None:
        self.sb.fake.reply(
            success(
                findings=[
                    {**SAMPLE_FINDING, "severity": "mineur", "line": None, "problem": "Nom trompeur"},
                    {**SAMPLE_FINDING, "severity": "bloquant", "problem": "Division par zéro non gérée"},
                ]
            )
        )

        report = self.sb.run("hostile-review", "main").stdout

        self.assertIn("F1 · app.py:2", section(report, "Bloquant"))
        self.assertIn("Division par zéro non gérée", section(report, "Bloquant"))
        self.assertEqual(section(report, "Important"), "Rien à signaler.")
        self.assertIn("F2 · app.py\n", section(report, "Mineur") + "\n")
        self.assertIn("Nom trompeur", section(report, "Mineur"))

    def test_findings_get_the_cli_identifiers_whatever_the_model_proposes(self) -> None:
        self.sb.fake.reply(
            success(
                findings=[
                    {**SAMPLE_FINDING, "id": "BUG-7"},
                    {**SAMPLE_FINDING, "id": "BUG-7", "problem": "Un second défaut"},
                ]
            )
        )

        report = self.sb.run("hostile-review", "main").stdout

        self.assertIn("### F1 · app.py:2", report)
        self.assertIn("### F2 · app.py:2", report)
        self.assertNotIn("BUG-7", report)

    def test_report_is_archived_outside_the_repository_and_its_path_comes_first(self) -> None:
        result = self.sb.run("hostile-review", "main")

        report = report_path(result.stdout)
        rest = result.stdout.partition("\n")[2]
        companion = report.with_suffix(".json")
        self.assertTrue(report.is_relative_to(self.sb.state / "claude-delegate"))
        self.assertEqual(report.read_text(encoding="utf-8"), rest.lstrip("\n"))
        self.assertEqual(json.loads(companion.read_text(encoding="utf-8"))["findings"][0]["id"], "F1")
        self.assertEqual({p.name for p in report.parent.iterdir()}, {report.name, companion.name})

    def test_report_header_says_what_was_reviewed_and_which_model_answered(self) -> None:
        self.sb.fake.reply(success(model="claude-opus-5-5-20261001"))
        merge_base = self.sb.git("merge-base", "main", "HEAD")

        report = self.sb.run("hostile-review", "main").stdout

        self.assertIn("| Modèle | claude-opus-5-5-20261001 |", report)
        self.assertIn(f"| Base | main (merge-base {merge_base[:12]}) |", report)
        self.assertRegex(report, r"\| Identifiant \| \d{8}T\d{6}Z-hostile-[0-9a-f]{6} \|")
        self.assertRegex(report, r"\| Date \(UTC\) \| \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \|")

    def test_report_header_says_how_the_review_ran(self) -> None:
        denial = {"tool_name": "Read", "tool_use_id": "t1", "tool_input": {"file_path": "/repo/.env"}}
        self.sb.fake.reply(
            {
                **success(),
                "num_turns": 7,
                "total_cost_usd": 1.234,
                "duration_ms": 65_000,
                "permission_denials": [denial],
            }
        )
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

        result = self.sb.run("hostile-review", "main")

        prompt = self.sb.fake.last_call()["system_prompt"] or ""
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        for row in [
            "| Type | revue hostile |",
            "| Effort | high |",
            "| Tours | 7 |",
            "| Coût estimé | 1,23 $ |",
            "| Durée | 1 min 05 s |",
            f"| Prompt | {prompt_sha[:12]} |",
            f"| Versions | claude-delegate {plugin['version']}, Claude Code 9.9.9 |",
            "| Permissions refusées | Read /repo/.env |",
        ]:
            self.assertIn(row, result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(companion["prompt_sha256"], prompt_sha)
        self.assertEqual(companion["claude_code_version"], "9.9.9")
        self.assertEqual(companion["permission_denials"], ["Read /repo/.env"])

    def test_run_details_nobody_reported_are_shown_as_unknown(self) -> None:
        unreported = ("num_turns", "total_cost_usd", "duration_ms", "permission_denials")
        self.sb.fake.reply({k: v for k, v in success().items() if k not in unreported})
        self.sb.fake.version(None)

        result = self.sb.run("hostile-review", "main")

        for row in [
            "| Tours | inconnu |",
            "| Coût estimé | inconnu |",
            "| Durée | inconnue |",
            "| Permissions refusées | inconnues |",
            "Claude Code inconnue |",
        ]:
            self.assertIn(row, result.stdout)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        for field in ("num_turns", "cost_usd", "duration_s", "permission_denials", "claude_code_version"):
            self.assertIsNone(companion[field], field)

    def test_malformed_run_details_do_not_crash_the_review(self) -> None:
        self.sb.fake.reply(
            {
                **success(),
                "num_turns": "abc",
                "total_cost_usd": "cher",
                "modelUsage": {"claude-opus-5-5": {"costUSD": None}, "claude-haiku-4-5": "oops"},
                "permission_denials": [{"tool_name": "Read", "tool_input": "/repo/.env"}, "oops"],
            }
        )

        result = self.sb.run("hostile-review", "main")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| Permissions refusées | Read /repo/.env |", result.stdout)

    def test_permission_denials_stay_readable_in_the_header(self) -> None:
        grep = {"tool_name": "Grep", "tool_input": {"pattern": "foo|bar\nbaz"}}
        reads = [{"tool_name": "Read", "tool_input": {"file_path": f"/x/{n}"}} for n in range(15)]
        self.sb.fake.reply({**success(), "permission_denials": [grep, grep, grep, *reads]})

        result = self.sb.run("hostile-review", "main")

        row = next(line for line in result.stdout.splitlines() if line.startswith("| Permissions refusées |"))
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 3, row)
        self.assertEqual(row.count("Grep"), 1)
        self.assertIn("(+6 autres)", row)
        companion = json.loads(report_path(result.stdout).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(len(companion["permission_denials"]), 16)

    def test_sonnet_can_be_requested_and_other_models_are_refused(self) -> None:
        self.sb.run("hostile-review", "main", "--model", "sonnet")

        self.assertEqual(option(self.sb.fake.last_call()["argv"], "--model"), "sonnet")
        refused = self.sb.run("hostile-review", "main", "--model", "haiku")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(len(self.sb.fake.calls()), 1)

    def test_reports_are_filed_under_the_origin_repository_without_credentials(self) -> None:
        expected = self.sb.state / "claude-delegate" / "github.com" / "linagora" / "claude-delegate"
        self.sb.git("remote", "add", "origin", "git@github.com:linagora/claude-delegate.git")
        for url in [
            "git@github.com:linagora/claude-delegate.git",
            "https://alice:ghp_secret@github.com/linagora/claude-delegate.git",
        ]:
            with self.subTest(url=url):
                self.sb.git("remote", "set-url", "origin", url)

                report = report_path(self.sb.run("hostile-review", "main").stdout)

                self.assertEqual(report.parent, expected)

    def test_reports_are_filed_under_origin_as_configured_not_as_rewritten(self) -> None:
        """An insteadOf rule (to a mirror, to SSH) does not change which repository origin names."""
        expected = self.sb.state / "claude-delegate" / "github.com" / "linagora" / "claude-delegate"
        self.sb.git("remote", "add", "origin", "https://github.com/linagora/claude-delegate.git")
        self.sb.git("config", f"url.{self.sb.root / 'miroir'}/.insteadOf", "https://github.com/")

        report = report_path(self.sb.run("hostile-review", "main").stdout)

        self.assertEqual(report.parent, expected)

    def test_default_base_is_the_default_branch_of_origin(self) -> None:
        origin = self.sb.root / "origin.git"
        self.sb.git("init", "-q", "--bare", "-b", "develop", str(origin), cwd=self.sb.root)
        self.sb.git("switch", "-q", "-c", "develop", "main")
        self.sb.write("develop.py", "DEVELOP_CHANGE = 1\n")
        self.sb.commit_all("develop work")
        self.sb.git("remote", "add", "origin", str(origin))
        self.sb.git("push", "-q", "origin", "develop")
        self.sb.git("remote", "set-head", "origin", "-a")
        self.sb.git("switch", "-q", "-c", "topic", "develop")
        self.sb.write("topic.py", "TOPIC_CHANGE = 1\n")
        self.sb.commit_all("topic work")

        result = self.sb.run("hostile-review")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| Base | origin/develop (merge-base", result.stdout)
        reviewed = self.sb.fake.last_call()["stdin"]
        self.assertIn("TOPIC_CHANGE", reviewed)
        self.assertNotIn("DEVELOP_CHANGE", reviewed)

    def test_default_base_falls_back_to_main_without_origin(self) -> None:
        result = self.sb.run("hostile-review")

        self.assertIn("| Base | main (merge-base", result.stdout)


if __name__ == "__main__":
    unittest.main()
