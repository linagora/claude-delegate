"""Test harness for the claude-delegate CLI.

Everything is exercised through the single agreed seam: the CLI run as a
process, in real temporary git repositories, with the `claude` binary
replaced by a recording fake (via CLAUDE_DELEGATE_BIN).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    "cwd_files": {{
        str(p): p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(Path(".").rglob("*"))
        if p.is_file() and ".git" not in p.parts and p.stat().st_size < 10_000
    }},
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


def option(argv: List[str], name: str) -> str:
    """The value given to a command-line option."""
    return argv[argv.index(name) + 1]


def recorded_calls(directory: Path) -> List[Any]:
    """The calls a fake recorded in `directory`, oldest first."""
    log = directory / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


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
        return recorded_calls(self.directory)

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


def interrupt_review(
    sb: Sandbox, args: Sequence[str], signum: int, extra_env: Optional[Dict[str, str]] = None
) -> Tuple[Dict[str, Any], int]:
    """Run the CLI, send it `signum` once the (sleeping) fake reviewer is
    called, and wait for it to exit: returns that reviewer call and the exit code."""
    process = subprocess.Popen(
        [sys.executable, str(BIN), *args],
        cwd=sb.repo,
        env={**sb.env(), **(extra_env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=_default_sigint,
    )
    try:
        deadline = time.monotonic() + 15
        while not sb.fake.calls() and time.monotonic() < deadline:
            time.sleep(0.05)
        call = sb.fake.last_call()
        process.send_signal(signum)
        process.communicate(timeout=15)
    finally:
        process.kill()
    return call, process.returncode


def _default_sigint() -> None:
    """A shell starts background jobs with SIGINT ignored, which the CLI would
    inherit when the suite runs in the background: Ctrl+C is restored."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


class FeatureBranchTestCase(unittest.TestCase):
    """A sandbox whose `feature` branch changes app.py in one commit on top of `main`."""

    def setUp(self) -> None:
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.init_repo()
        self.sb.git("switch", "-q", "-c", "feature")
        self.sb.write("app.py", "def div(a, b):\n    return a / b if b else 0\n")
        self.sb.commit_all("feature change")


_FAKE_GH_SCRIPT = '''#!{python}
import json, sys
from pathlib import Path

here = Path({directory!r})
with open(here / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
reply = json.loads((here / "reply.json").read_text(encoding="utf-8"))
sys.stdout.write(reply["stdout"])
sys.stderr.write(reply["stderr"])
sys.exit(reply["exit_code"])
'''


class FakeGh:
    """Stand-in for `gh`, placed first on the PATH: records each call, replies with a canned result."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        self.directory = directory
        path = directory / "gh"
        path.write_text(_FAKE_GH_SCRIPT.format(python=sys.executable, directory=str(directory)), encoding="utf-8")
        path.chmod(0o755)
        self.reply({})

    def reply(self, payload: Dict[str, Any]) -> None:
        self._write(json.dumps(payload), "", 0)

    def fail(self, stderr: str) -> None:
        self._write("", stderr, 1)

    def _write(self, stdout: str, stderr: str, exit_code: int) -> None:
        reply = {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        (self.directory / "reply.json").write_text(json.dumps(reply), encoding="utf-8")

    def calls(self) -> List[List[str]]:
        return recorded_calls(self.directory)


class PullRequestTestCase(unittest.TestCase):
    """A repository whose origin looks like GitHub, holding pull request #7 from a contributor."""

    NUMBER = "7"
    URL = "https://github.com/acme/app.git"

    def setUp(self) -> None:
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.init_repo()
        self.origin = self.sb.root / "origin.git"
        self.sb.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.sb.root)
        self.sb.git("config", f"url.{self.origin}.insteadOf", self.URL)
        self.sb.git("remote", "add", "origin", self.URL)
        self.sb.git("push", "-q", "origin", "main")
        self.contributor = self.sb.root / "contributor"
        self.sb.git("clone", "-q", str(self.origin), str(self.contributor), cwd=self.sb.root)
        self.gh = FakeGh(self.sb.root / "gh-bin")
        self.update_pull_request({"app.py": "def div(a, b):\n    return a / b if b else PR_CHANGE\n"})

    def update_pull_request(self, files: Dict[str, str]) -> None:
        """Commit `files` on top of origin's main in the contributor's clone and
        publish them as refs/pull/7/head only, as from a fork: the repository
        under review only gets them by fetching. gh then describes that head."""
        self.head = self._publish_from_contributor(files, f"refs/pull/{self.NUMBER}/head")
        self.gh.reply(self.metadata())

    def move_target_branch(self, files: Dict[str, str]) -> None:
        """Someone else merges `files` into main on the forge."""
        self._publish_from_contributor(files, "refs/heads/main")

    def _publish_from_contributor(self, files: Dict[str, str], ref: str) -> str:
        clone = self.contributor
        self.sb.git("fetch", "-q", "origin", cwd=clone)
        self.sb.git("switch", "-q", "--detach", "origin/main", cwd=clone)
        for name, content in files.items():
            path = clone / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.sb.git("add", "-A", cwd=clone)
        self.sb.git("commit", "-q", "-m", "contributor work", cwd=clone)
        self.sb.git("push", "-q", "-f", "origin", f"HEAD:{ref}", cwd=clone)
        return self.sb.git("rev-parse", "HEAD", cwd=clone)

    def metadata(self, **fields: Any) -> Dict[str, Any]:
        return {
            "title": "Gérer la division par zéro",
            "body": "Cette PR renvoie PR_CHANGE quand b vaut zéro.",
            "baseRefName": "main",
            "headRefOid": self.head,
            "url": f"https://github.com/acme/app/pull/{self.NUMBER}",
            **fields,
        }

    def path_with_gh(self) -> str:
        return f"{self.gh.directory}{os.pathsep}{os.environ['PATH']}"

    def run_pr(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.sb.run("pr-review", self.NUMBER, *args, extra_env={"PATH": self.path_with_gh()})
