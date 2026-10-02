"""Launching the delegated Claude Code session, isolated and read-only."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from . import policy
from .errors import DelegateError

#: The plugin's prompts. ${CLAUDE_PLUGIN_ROOT} is not exported to the shell, so
#: the CLI finds them from its own location.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

#: Reads the reviewer must never perform, even inside the reviewed tree.
DENIED_READS = [f"Read({path})" for path in policy.DENIED_PATHS]

#: The only variables the reviewer inherits (plus LC_*). Anything else, such as
#: the DeepSeek ANTHROPIC_* settings, CLAUDE_CODE_* tuning or tokens, stays out.
PASSED_ENV = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "TERM", "TMPDIR")

MODEL = "opus"
EFFORT = "high"
#: Bounds on what one review may consume from the user's quota.
MAX_TURNS = 30
MAX_BUDGET_USD = 5


def launch(
    root: Path, task_input: str, schema: Dict[str, Any], prompt_file: Path, instruction: str
) -> "subprocess.CompletedProcess[str]":
    """Run the reviewer in `root` on `task_input` and return its raw result."""
    binary = resolve_binary()
    try:
        return subprocess.run(
            _command(binary, schema, prompt_file, instruction),
            input=task_input,
            cwd=root,
            env=_environment(),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        raise DelegateError(f"binaire claude introuvable ou non exécutable : {binary} ({error.strerror})") from None


def resolve_binary() -> str:
    """CLAUDE_DELEGATE_BIN, else the native install, else the first `claude` on PATH
    that is not a cmux shim (cmux injects its own --settings and --session-id)."""
    override = os.environ.get("CLAUDE_DELEGATE_BIN")
    if override:
        return override
    native = Path.home() / ".local" / "bin" / "claude"
    if _is_executable(native):
        return str(native)
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "claude"
        if directory and _is_executable(candidate) and not _is_cmux_shim(candidate):
            return str(candidate)
    raise DelegateError("binaire claude introuvable : installez Claude Code ou définissez CLAUDE_DELEGATE_BIN")


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _is_cmux_shim(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(65536)
    except OSError:
        return False
    return head.startswith(b"#!") and b"cmux" in head


def _environment() -> Dict[str, str]:
    """Rebuilt from scratch, with a dedicated config dir holding the Anthropic login."""
    env = {k: v for k, v in os.environ.items() if k in PASSED_ENV or k.startswith("LC_")}
    env["CLAUDE_CONFIG_DIR"] = str(Path.home() / ".claude-anthropic")
    return env


def _command(binary: str, schema: Dict[str, Any], prompt_file: Path, instruction: str) -> List[str]:
    """The isolation contract, validated against a booby-trapped project (probe V1).

    --restricted ignores user, project and local settings files (env blocks,
    allow rules, hooks), removes shell and web tools and confines reads to
    the working directory; --tools leaves only read-only tools.
    """
    return [
        binary,
        "-p",
        "--restricted",
        "--tools",
        "Read,Grep,Glob",
        "--strict-mcp-config",
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
        "--settings",
        json.dumps({"permissions": {"deny": DENIED_READS}}),
        "--model",
        MODEL,
        "--effort",
        EFFORT,
        "--max-turns",
        str(MAX_TURNS),
        "--max-budget-usd",
        str(MAX_BUDGET_USD),
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--append-system-prompt-file",
        str(prompt_file),
        instruction,
    ]
