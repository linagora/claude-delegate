"""The launcher of Claude Code on DeepSeek, run as a process with fakes of
claude, security, secret-tool and uname first on the PATH."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from tests.support import ROOT

LAUNCHER = ROOT / "bin" / "claude-deepseek"

GATEWAY = "https://ai-api.linagora.com"
GATEWAY_MODEL = "deepseek-v4.1-flash"
KEY_SERVICE = "linagora-ai-api-key"
MODEL_VARIABLES = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]

#: Prints what Claude Code would start with.
_FAKE_CLAUDE = """#!{python}
import json, os, sys
names = [name for name in os.environ if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "BASH_DEFAULT"))]
print(json.dumps({{"argv": sys.argv[1:], "env": {{name: os.environ[name] for name in names}}}}))
"""

#: `security find-generic-password -s <service> -w` and
#: `secret-tool lookup service <service>`, both reading keychain.json.
_FAKE_KEYCHAIN = """#!{python}
import json, sys
argv = sys.argv[1:]
service = argv[argv.index("-s") + 1] if "-s" in argv else argv[argv.index("service") + 1]
key = json.load(open({keychain!r})).get(service)
if key is None:
    sys.exit(44)
print(key)
"""

_FAKE_UNAME = """#!/bin/sh
cat {system!r}
"""


class LauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.keychain_file = self.root / "keychain.json"
        self.system_file = self.root / "system.txt"
        fakes = {
            "claude": _FAKE_CLAUDE.format(python=sys.executable),
            "security": _FAKE_KEYCHAIN.format(python=sys.executable, keychain=str(self.keychain_file)),
            "secret-tool": _FAKE_KEYCHAIN.format(python=sys.executable, keychain=str(self.keychain_file)),
            "uname": _FAKE_UNAME.format(system=str(self.system_file)),
        }
        for name, script in fakes.items():
            path = self.bin / name
            path.write_text(script, encoding="utf-8")
            path.chmod(0o755)
        self.store({KEY_SERVICE: "CLE_DE_TEST"})
        self.system("Darwin")

    def store(self, keys: Dict[str, str]) -> None:
        self.keychain_file.write_text(json.dumps(keys), encoding="utf-8")

    def system(self, name: str) -> None:
        self.system_file.write_text(name + "\n", encoding="utf-8")

    def launch(self, *args: str, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess[str]:
        environment = {"PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.root)}
        return subprocess.run(
            [str(LAUNCHER), *args], env={**environment, **(env or {})}, capture_output=True, text=True
        )

    def started(self, result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stderr)
        started: Dict[str, Any] = json.loads(result.stdout)
        return started

    def test_claude_code_goes_to_the_linagora_gateway_with_the_keychain_key(self) -> None:
        started = self.started(self.launch("--resume", "abc"))

        env = started["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], GATEWAY)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "CLE_DE_TEST")
        # A gateway key may reach no other model: background tasks and
        # subagents asking for a Claude model would be refused.
        self.assertEqual({env[name] for name in MODEL_VARIABLES}, {GATEWAY_MODEL})
        self.assertEqual(env["BASH_DEFAULT_TIMEOUT_MS"], "900000")
        self.assertEqual(started["argv"], ["--dangerously-skip-permissions", "--resume", "abc"])

    def test_without_a_key_nothing_starts_and_the_way_to_store_one_is_given(self) -> None:
        self.store({})

        result = self.launch()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"security add-generic-password -a \"$USER\" -s {KEY_SERVICE} -w", result.stderr)

    def test_a_key_in_the_environment_is_used_as_on_a_server(self) -> None:
        started = self.started(self.launch(env={"LINAGORA_API_KEY": "CLE_ENV"}))

        self.assertEqual(started["env"]["ANTHROPIC_AUTH_TOKEN"], "CLE_ENV")

    def test_on_linux_the_key_comes_from_secret_tool(self) -> None:
        self.system("Linux")
        self.store({KEY_SERVICE: "CLE_LINUX"})

        started = self.started(self.launch())

        self.assertEqual(started["env"]["ANTHROPIC_AUTH_TOKEN"], "CLE_LINUX")

    def test_deepseek_s_own_api_can_be_chosen_instead(self) -> None:
        self.store({"deepseek-api-key": "CLE_DEEPSEEK"})

        started = self.started(
            self.launch(
                env={
                    "CLAUDE_DEEPSEEK_BASE_URL": "https://api.deepseek.com/anthropic",
                    "CLAUDE_DEEPSEEK_MODEL": "deepseek-flash",
                    "CLAUDE_DEEPSEEK_KEY_SERVICE": "deepseek-api-key",
                }
            )
        )

        env = started["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.deepseek.com/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "CLE_DEEPSEEK")
        self.assertEqual({env[name] for name in MODEL_VARIABLES}, {"deepseek-flash"})

    def test_a_timeout_already_chosen_is_kept(self) -> None:
        started = self.started(self.launch(env={"BASH_DEFAULT_TIMEOUT_MS": "1200000"}))

        self.assertEqual(started["env"]["BASH_DEFAULT_TIMEOUT_MS"], "1200000")

    def test_the_effort_parameter_is_forced_because_the_gateway_model_is_unknown(self) -> None:
        # Claude Code sends no effort parameter to a model it does not
        # recognise as effort-capable, which is the case behind a gateway.
        started = self.started(self.launch())

        self.assertEqual(started["env"]["CLAUDE_CODE_ALWAYS_ENABLE_EFFORT"], "1")

    def test_permissions_are_bypassed_and_the_choice_can_be_reversed(self) -> None:
        bypassed = self.started(self.launch("--resume", "abc"))
        asked = self.started(self.launch("--resume", "abc", env={"CLAUDE_DEEPSEEK_ASK_PERMISSIONS": "1"}))

        self.assertEqual(bypassed["argv"], ["--dangerously-skip-permissions", "--resume", "abc"])
        self.assertEqual(asked["argv"], ["--resume", "abc"])

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
    def test_the_launcher_passes_shellcheck(self) -> None:
        done = subprocess.run(["shellcheck", str(LAUNCHER)], capture_output=True, text=True)

        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
