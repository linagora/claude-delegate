"""The delegated Claude Code session: how it is launched and what it returns."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from . import schemas
from .errors import DelegateError
from .gitctx import HostileContext


#: The plugin's prompts. ${CLAUDE_PLUGIN_ROOT} is not exported to the shell, so
#: the CLI finds them from its own location.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

#: Reads the reviewer must never perform, even inside the reviewed tree.
DENIED_READS = ["Read(**/.env)", "Read(**/.env.*)", "Read(**/.claude/settings*.json)"]

#: The only variables the reviewer inherits (plus LC_*). Anything else, such as
#: the DeepSeek ANTHROPIC_* settings, CLAUDE_CODE_* tuning or tokens, stays out.
PASSED_ENV = ("HOME", "USER", "LOGNAME", "PATH", "LANG", "TERM", "TMPDIR")

MODEL = "opus"
EFFORT = "high"
#: Bounds on what one review may consume from the user's quota.
MAX_TURNS = 30
MAX_BUDGET_USD = 5


@dataclass(frozen=True)
class Review:
    summary: str
    findings: List[Dict[str, Any]]
    model: str


def review(ctx: HostileContext) -> Review:
    binary = resolve_binary()
    try:
        done = subprocess.run(
            _command(binary, "Revue hostile du diff fourni sur l'entrée standard."),
            input=ctx.diff,
            cwd=ctx.root,
            env=_environment(),
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise DelegateError(f"binaire claude introuvable ou non exécutable : {binary} ({error.strerror})") from None
    return _interpret(done)


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


def _interpret(done: "subprocess.CompletedProcess[str]") -> Review:
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        raise DelegateError(
            f"sortie illisible du délégué (code {done.returncode}) : {_excerpt(done.stdout or done.stderr)}"
        ) from None
    if not isinstance(payload, dict):
        raise DelegateError(f"sortie inattendue du délégué : {_excerpt(done.stdout)}")
    if payload.get("is_error") or payload.get("subtype") != "success" or done.returncode != 0:
        reason = payload.get("result") or payload.get("subtype") or f"code {done.returncode}"
        raise DelegateError(f"la revue a échoué : {_excerpt(str(reason))}")
    structured = payload.get("structured_output")
    if not isinstance(structured, dict) or not schemas.is_review(structured):
        raise DelegateError("la sortie structurée du délégué est absente ou non conforme au schéma")
    return Review(
        summary=structured["summary"],
        findings=_numbered(structured["findings"]),
        model=_model(payload),
    )


def _excerpt(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _model(payload: Dict[str, Any]) -> str:
    """The model that actually answered: the costliest entry of modelUsage."""
    usage = payload.get("modelUsage") or {}
    if not usage:
        return "inconnu"
    return str(max(usage, key=lambda name: (usage[name] or {}).get("costUSD", 0)))


def _numbered(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Most severe first (model order kept within a severity), numbered F1, F2…"""
    ordered = sorted(findings, key=lambda f: schemas.SEVERITIES.index(f["severity"]))
    return [{"id": f"F{n}", **finding} for n, finding in enumerate(ordered, start=1)]


def _environment() -> Dict[str, str]:
    """Rebuilt from scratch, with a dedicated config dir holding the Anthropic login."""
    env = {k: v for k, v in os.environ.items() if k in PASSED_ENV or k.startswith("LC_")}
    env["CLAUDE_CONFIG_DIR"] = str(Path.home() / ".claude-anthropic")
    return env


def _command(binary: str, prompt: str) -> List[str]:
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
        json.dumps(schemas.HOSTILE_REVIEW),
        "--append-system-prompt-file",
        str(PROMPTS / "hostile-review.md"),
        prompt,
    ]
