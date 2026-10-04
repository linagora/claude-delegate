"""Static checks of the plugin's slash commands and manifests.

A command whose `allowed-tools` does not cover its `!` invocation is silently
aborted by Claude Code: that is checked here.

A command the model may invoke lets the worker session trigger a delegation on
its own, and spend Claude money without being asked. The four delegating
commands are deliberately model-invocable, each with a `description` that says
the natural-language request that triggers it, and the reviewer's shared prompt
carries the budget that bounds them. `selftest` stays human-only: it is the
isolation probe, and must remain a deliberate act.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

from tests.support import BIN, PLUGIN, ROOT

PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"


def parse_command(path: Path) -> Tuple[Dict[str, str], str]:
    """Frontmatter (flat `key: value` pairs) and body of a command file."""
    _, frontmatter, body = path.read_text(encoding="utf-8").split("---\n", 2)
    fields = {}
    for line in frontmatter.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


def shell_invocations(body: str) -> List[str]:
    return re.findall(r"!`([^`]+)`", body)


def tool_rules(allowed_tools: str) -> List[str]:
    """`Bash(x:*), Write` -> ["Bash(x:*)", "Write"]."""
    return re.findall(r"[A-Za-z]+(?:\([^)]*\))?", allowed_tools)


def rule_for(invocation: str) -> str:
    """The narrowest rule allowing an invocation, whatever arguments the user types."""
    return f"Bash({invocation.removesuffix(' $ARGUMENTS')}:*)"


class PluginCommandsTest(unittest.TestCase):
    def test_the_marketplace_lists_the_delegate_plugin_at_the_cli_version(self) -> None:
        marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        [entry] = [p for p in marketplace["plugins"] if p["name"] == "delegate"]
        manifest = json.loads(
            (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        version = subprocess.run([str(BIN), "--version"], capture_output=True, text=True).stdout.split()[-1]
        self.assertEqual((ROOT / entry["source"]).resolve(), PLUGIN)
        self.assertEqual(manifest["name"], "delegate")
        self.assertEqual(manifest["version"], version)

    def test_commands_are_allowed_exactly_their_invocations(self) -> None:
        commands = sorted((PLUGIN / "commands").glob("*.md"))
        self.assertTrue(commands)
        for command in commands:
            with self.subTest(command.name):
                fields, body = parse_command(command)
                self.assertEqual(
                    sorted(tool_rules(fields.get("allowed-tools", ""))),
                    sorted(rule_for(invocation) for invocation in shell_invocations(body)),
                )

    def test_commands_delegating_to_claude_are_model_invocable_and_selftest_is_not(self) -> None:
        for command in sorted((PLUGIN / "commands").glob("*.md")):
            fields, body = parse_command(command)
            with self.subTest(command.name):
                if command.name == "selftest.md":
                    # The isolation probe: still triggered by the user alone.
                    self.assertEqual(fields.get("disable-model-invocation"), "true")
                    continue
                # The natural-language request that triggers the delegation
                # must be spelled out, or the model has nothing to match on.
                self.assertNotIn("disable-model-invocation", fields)
                self.assertIn("À déclencher quand", fields["description"])
                if shell_invocations(body):
                    # A review the model can trigger spends Opus money: the
                    # reviewer is told when to stop.
                    self.assertTrue(fields["description"].endswith("."))

    def test_invocations_target_the_executable_cli_and_one_of_its_subcommands(self) -> None:
        for command in sorted((PLUGIN / "commands").glob("*.md")):
            for invocation in shell_invocations(parse_command(command)[1]):
                with self.subTest(command.name):
                    program, subcommand, *_ = invocation.replace(PLUGIN_ROOT_VAR, str(PLUGIN)).split()
                    done = subprocess.run([program, subcommand, "--help"], capture_output=True, text=True)
                    self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_hostile_review_command_exists(self) -> None:
        _, body = parse_command(PLUGIN / "commands" / "hostile-review.md")
        self.assertEqual(
            shell_invocations(body),
            [f"{PLUGIN_ROOT_VAR}/bin/claude-delegate hostile-review $ARGUMENTS"],
        )

    def test_the_pr_review_command_checks_findings_at_the_reviewed_head_and_publishes_nothing(self) -> None:
        fields, body = parse_command(PLUGIN / "commands" / "pr-review.md")

        self.assertIn("merge request GitLab", fields["description"])
        self.assertIn("--forge", fields["argument-hint"])

        self.assertEqual(
            shell_invocations(body),
            [f"{PLUGIN_ROOT_VAR}/bin/claude-delegate pr-review $ARGUMENTS"],
        )
        self.assertIn("git show", body)
        self.assertIn("aucun checkout", body)
        self.assertIn("« Tête »", body)
        self.assertIn("« Fichiers non relus »", body)
        self.assertIn("Ne publie rien", body)

    def test_the_recheck_command_sums_up_the_statuses_and_what_remains_blocking(self) -> None:
        _, body = parse_command(PLUGIN / "commands" / "recheck.md")

        self.assertEqual(
            shell_invocations(body),
            [f"{PLUGIN_ROOT_VAR}/bin/claude-delegate recheck $ARGUMENTS"],
        )
        self.assertIn("« Constats d'origine »", body)
        self.assertIn("reste bloquant", body)
        # A recheck of a pull request is checked at its head, without a checkout.
        self.assertIn("git show", body)
        self.assertIn("« Fichiers non relus »", body)

    def test_the_reviewer_budget_is_in_the_shared_security_fragment(self) -> None:
        security = (PLUGIN / "prompts" / "security.md").read_text(encoding="utf-8")

        self.assertIn("deux revues par tour", security)
        self.assertIn("recheck", security)

    def test_handoff_writes_a_dated_brief_without_shell_and_points_to_a_spec_session(self) -> None:
        _, body = parse_command(PLUGIN / "commands" / "handoff.md")

        self.assertEqual(shell_invocations(body), [])
        self.assertIn("docs/specs/brief-AAAAMMJJ-", body)
        self.assertIn("[a-z0-9-]", body)
        for section in [
            "## Contexte",
            "## Objectif",
            "## Décisions déjà prises",
            "## Contraintes",
            "## Questions ouvertes",
            "## Fichiers et références",
        ]:
            self.assertIn(section, body)
        self.assertIn("session Claude Code sur Anthropic", body)
        self.assertLess(body.index("grill-me"), body.index("to-spec"))


if __name__ == "__main__":
    unittest.main()
