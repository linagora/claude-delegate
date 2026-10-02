"""Test harness for the claude-delegate CLI.

Everything is exercised through the single agreed seam: the CLI run as a
process, in real temporary git repositories, with the `claude` binary
replaced by a recording fake (via CLAUDE_DELEGATE_BIN).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "delegate"
BIN = PLUGIN / "bin" / "claude-delegate"

SAMPLE_FINDING = {
    "severity": "bloquant",
    "file": "app.py",
    "line": 2,
    "problem": "Division par zéro non gérée",
    "failure_scenario": "div(1, 0) lève ZeroDivisionError en production",
    "fix": "Valider b avant la division",
}

_FAKE_SCRIPT = '''#!{python}
import json, os, sys, time
from pathlib import Path

here = Path({directory!r})
argv = sys.argv[1:]
if argv == ["--version"]:
    version = here / "version.txt"
    if not version.exists():
        sys.exit(1)
    print(version.read_text(encoding="utf-8"))
    sys.exit(0)
prompt_file = None
if "--append-system-prompt-file" in argv:
    prompt_file = Path(argv[argv.index("--append-system-prompt-file") + 1])
call = {{
    "argv": argv,
    "env": dict(os.environ),
    "cwd": os.getcwd(),
    "cwd_listing": sorted(os.listdir(".")),
    "stdin": sys.stdin.read(),
    "system_prompt": prompt_file.read_text(encoding="utf-8") if prompt_file else None,
}}
with open(here / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(call) + "\\n")
queue = json.loads((here / "reply.json").read_text(encoding="utf-8"))["queue"]
reply = queue.pop(0) if len(queue) > 1 else queue[0]
(here / "reply.json").write_text(json.dumps({{"queue": queue}}), encoding="utf-8")
time.sleep(reply.get("sleep", 0))
for name in reply.get("touch", []):
    Path(name).parent.mkdir(parents=True, exist_ok=True)
    Path(name).touch()
sys.stdout.write(reply["stdout"])
sys.exit(reply["exit_code"])
'''


def success(
    findings: Optional[List[Dict[str, Any]]] = None,
    summary: str = "Une division par zéro est possible.",
    model: str = "claude-opus-5-5",
) -> Dict[str, Any]:
    """A `claude -p --output-format json` result carrying structured output."""
    structured = {"summary": summary, "findings": [SAMPLE_FINDING] if findings is None else findings}
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 3,
        "result": json.dumps(structured),
        "structured_output": structured,
        "total_cost_usd": 0.42,
        "modelUsage": {model: {"inputTokens": 1000, "outputTokens": 200, "costUSD": 0.42}},
        "permission_denials": [],
        "terminal_reason": "completed",
        "session_id": "test-session",
    }


def report_path(stdout: str) -> Path:
    """The archived report announced on the first line of the CLI output."""
    first_line = stdout.partition("\n")[0]
    assert first_line.startswith("Rapport : "), first_line
    return Path(first_line[len("Rapport : ") :])


class FakeClaude:
    """Stand-in for the `claude` binary: records each call, replies with a canned result."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        self.directory = directory
        self.path = directory / "claude"
        self.path.write_text(
            _FAKE_SCRIPT.format(python=sys.executable, directory=str(directory)), encoding="utf-8"
        )
        self.path.chmod(0o755)
        self.reply(success())
        self.version("9.9.9 (Claude Code)")

    def version(self, text: Optional[str]) -> None:
        """What `claude --version` prints; None makes it fail."""
        version = self.directory / "version.txt"
        if text is None:
            version.unlink(missing_ok=True)
        else:
            version.write_text(text, encoding="utf-8")

    def reply(
        self, payload: Dict[str, Any], exit_code: int = 0, touch: Sequence[str] = (), sleep: float = 0
    ) -> None:
        """Answer with `payload`; `touch` files (relative to the cwd) are created
        first, as a reviewer that managed to write would, after `sleep` seconds."""
        self.reply_raw(json.dumps(payload), exit_code, touch, sleep)

    def reply_raw(
        self, stdout: str, exit_code: int = 0, touch: Sequence[str] = (), sleep: float = 0
    ) -> None:
        self._queue([{"stdout": stdout, "exit_code": exit_code, "touch": list(touch), "sleep": sleep}])

    def replies(self, *payloads: Dict[str, Any]) -> None:
        """Answer successive calls with successive payloads; the last one then repeats."""
        self._queue([{"stdout": json.dumps(p), "exit_code": 0, "touch": []} for p in payloads])

    def _queue(self, replies: List[Dict[str, Any]]) -> None:
        (self.directory / "reply.json").write_text(json.dumps({"queue": replies}), encoding="utf-8")

    def calls(self) -> List[Dict[str, Any]]:
        log = self.directory / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def last_call(self) -> Dict[str, Any]:
        calls = self.calls()
        assert calls, "the fake claude was never called"
        return calls[-1]


class Sandbox:
    """A throwaway HOME, state dir, git repository and fake claude."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.state = self.root / "state"
        self.repo = self.root / "repo"
        self.fake = FakeClaude(self.root / "fake")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def env(self) -> Dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.state),
            "CLAUDE_DELEGATE_BIN": str(self.fake.path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }

    def git(self, *args: str, cwd: Optional[Path] = None) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            env=self.env(),
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit_all(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def init_repo(self) -> None:
        """A repository whose `main` holds one commit."""
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "def div(a, b):\n    return a / b\n")
        self.commit_all("initial")

    def run(
        self,
        *args: str,
        extra_env: Optional[Dict[str, str]] = None,
        unset: Sequence[str] = (),
        cwd: Optional[Path] = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {**self.env(), **(extra_env or {})}
        for name in unset:
            env.pop(name, None)
        return subprocess.run(
            [sys.executable, str(BIN), *args],
            cwd=cwd or self.repo,
            env=env,
            capture_output=True,
            text=True,
        )


class FeatureBranchTestCase(unittest.TestCase):
    """A sandbox whose `feature` branch changes app.py in one commit on top of `main`."""

    def setUp(self) -> None:
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.init_repo()
        self.sb.git("switch", "-q", "-c", "feature")
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else 0\n")
        self.sb.commit_all("feature change")
