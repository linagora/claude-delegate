"""Reading the delegated session's result: failures, schema validation, numbering."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import schemas
from .errors import EXIT_INCOMPLETE, EXIT_INVALID_OUTPUT, EXIT_QUOTA, DelegateError

#: How Claude Code reports a usage limit, e.g. "You've hit your weekly limit ·
#: resets Oct 6 at 10am (Europe/Paris)", "You're out of extra usage · resets 3pm"
#: or "5-hour limit reached ∙ resets 3pm".
_USAGE_LIMIT = re.compile(r"hit your [^\n]*limit|limit reached|out of (?:extra )?usage", re.IGNORECASE)
#: The reset time ends at the end of the line or at the next separator.
_RESETS = re.compile(r"\bresets\s+([^\n·∙|]+)", re.IGNORECASE)

#: The reviewer's dedicated config dir has no Anthropic login yet.
_NOT_LOGGED_IN = re.compile(r"not logged in|please run /login|invalid api key", re.IGNORECASE)

#: Results cut short by the review's own caps.
_INCOMPLETE = {
    "error_max_budget_usd": "revue incomplète : plafond de budget atteint",
    "error_max_turns": "revue incomplète : nombre maximal de tours atteint",
}

_INVALID_OUTPUT = "la sortie structurée du délégué est absente ou non conforme au schéma"
#: Claude Code gave up producing output that matches the schema.
_OUTPUT_RETRIES_EXHAUSTED = "error_max_structured_output_retries"


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    file: str
    line: Optional[int]
    problem: str
    failure_scenario: str
    fix: str

    @property
    def location(self) -> str:
        return self.file if self.line is None else f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Review:
    summary: str
    findings: List[Finding]
    model: str
    num_turns: Optional[int]
    cost_usd: Optional[float]
    duration_s: Optional[float]
    #: None when the result does not say (unlike an empty list: none refused).
    permission_denials: Optional[List[str]]


def read_result(done: "subprocess.CompletedProcess[str]") -> Dict[str, Any]:
    """The delegated session's JSON result, or a typed DelegateError when it failed."""
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        raise DelegateError(
            f"sortie illisible du délégué (code {done.returncode}) : {_excerpt(done.stdout or done.stderr)}"
        ) from None
    if not isinstance(payload, dict):
        raise DelegateError(f"sortie inattendue du délégué : {_excerpt(done.stdout)}")
    _raise_on_failure(payload, done.returncode)
    return payload


def read_review(done: "subprocess.CompletedProcess[str]") -> Review:
    payload = read_result(done)
    return _review(payload, _structured_output(payload, schemas.is_review))


def _structured_output(payload: Dict[str, Any], honours: Callable[[Any], bool]) -> Dict[str, Any]:
    structured = payload.get("structured_output")
    if not isinstance(structured, dict) or not honours(structured):
        raise DelegateError(_INVALID_OUTPUT, EXIT_INVALID_OUTPUT)
    return structured


def _review(payload: Dict[str, Any], structured: Dict[str, Any]) -> Review:
    cost = payload.get("total_cost_usd")
    duration = payload.get("duration_ms")
    refused = refusals(payload)
    return Review(
        summary=structured["summary"],
        findings=_numbered(structured["findings"]),
        model=_model(payload),
        num_turns=_int_or_none(payload.get("num_turns")),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        duration_s=duration / 1000 if isinstance(duration, (int, float)) else None,
        permission_denials=(
            # Deduplicated, in order: the reviewer often retries a refused call.
            list(dict.fromkeys(f"{tool} {target}".strip() for tool, target in refused))
            if refused is not None
            else None
        ),
    )


def _int_or_none(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def refusals(payload: Dict[str, Any]) -> Optional[List[Tuple[str, str]]]:
    """(tool, target) for each permission the session was refused, such as
    ("Read", "/repo/.env"); None when the result does not say."""
    denials = payload.get("permission_denials")
    if not isinstance(denials, list):
        return None
    return [_refusal(denial) for denial in denials if isinstance(denial, dict)]


def _refusal(denial: Dict[str, Any]) -> Tuple[str, str]:
    target = denial.get("tool_input")
    if isinstance(target, dict):
        what = next((str(target[k]) for k in ("file_path", "path", "pattern", "command") if target.get(k)), "")
    else:
        what = target if isinstance(target, str) else ""
    return str(denial.get("tool_name", "?")), what


def _raise_on_failure(payload: Dict[str, Any], returncode: int) -> None:
    subtype = payload.get("subtype")
    if subtype in _INCOMPLETE:
        raise DelegateError(_INCOMPLETE[subtype], EXIT_INCOMPLETE)
    if subtype == _OUTPUT_RETRIES_EXHAUSTED:
        raise DelegateError(f"{_INVALID_OUTPUT} (tentatives épuisées)", EXIT_INVALID_OUTPUT)
    if not payload.get("is_error") and subtype == "success" and returncode == 0:
        return
    errors = payload.get("errors")
    details = "; ".join(str(e) for e in errors) if isinstance(errors, list) else ""
    reason = str(payload.get("result") or details or subtype or f"code {returncode}")
    if _USAGE_LIMIT.search(reason):
        resets = _RESETS.search(reason)
        when = f" (reprise : {resets.group(1).strip().rstrip('.')})" if resets else ""
        raise DelegateError(f"quota Claude épuisé{when}", EXIT_QUOTA)
    if _NOT_LOGGED_IN.search(reason):
        raise DelegateError(
            "le relecteur n'est pas connecté à Anthropic : lance une fois "
            "`CLAUDE_CONFIG_DIR=~/.claude-anthropic claude`, puis /login"
        )
    if payload.get("api_error_status") == 429:
        raise DelegateError(f"limite de débit Claude atteinte : {_excerpt(reason)}", EXIT_QUOTA)
    raise DelegateError(f"la revue a échoué : {_excerpt(reason)}")


def _numbered(findings: List[Dict[str, Any]]) -> List[Finding]:
    """Most severe first (model order kept within a severity), numbered F1, F2…
    Only the schema fields are kept: an identifier proposed by the model is dropped."""
    ordered = sorted(findings, key=lambda f: schemas.SEVERITIES.index(f["severity"]))
    return [
        Finding(
            id=f"F{n}",
            severity=f["severity"],
            file=f["file"],
            line=f["line"],
            problem=f["problem"],
            failure_scenario=f["failure_scenario"],
            fix=f["fix"],
        )
        for n, f in enumerate(ordered, start=1)
    ]


def _model(payload: Dict[str, Any]) -> str:
    """The model that actually answered: the costliest entry of modelUsage."""
    usage = payload.get("modelUsage")
    if not isinstance(usage, dict) or not usage:
        return "inconnu"

    def cost(name: str) -> float:
        entry = usage[name]
        value = entry.get("costUSD") if isinstance(entry, dict) else None
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    return str(max(usage, key=cost))


def _excerpt(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
