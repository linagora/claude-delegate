"""Reading the delegated session's result: failures, schema validation, numbering."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import schemas
from .errors import EXIT_INCOMPLETE, EXIT_INVALID_OUTPUT, EXIT_QUOTA, DelegateError

#: How Claude Code reports a usage limit, e.g. "You've hit your weekly limit ·
#: resets Oct 6 at 10am (Europe/Paris)", "You're out of extra usage · resets 3pm"
#: or "5-hour limit reached ∙ resets 3pm".
_USAGE_LIMIT = re.compile(r"hit your [^\n]*limit|limit reached|out of (?:extra )?usage", re.IGNORECASE)
#: The reset time ends at the end of the line or at the next separator.
_RESETS = re.compile(r"\bresets\s+([^\n·∙|]+)", re.IGNORECASE)

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
    num_turns: int
    cost_usd: Optional[float]
    duration_s: Optional[float]
    permission_denials: List[str]


def read_review(done: "subprocess.CompletedProcess[str]") -> Review:
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        raise DelegateError(
            f"sortie illisible du délégué (code {done.returncode}) : {_excerpt(done.stdout or done.stderr)}"
        ) from None
    if not isinstance(payload, dict):
        raise DelegateError(f"sortie inattendue du délégué : {_excerpt(done.stdout)}")
    _raise_on_failure(payload, done.returncode)
    structured = payload.get("structured_output")
    if not isinstance(structured, dict) or not schemas.is_review(structured):
        raise DelegateError(_INVALID_OUTPUT, EXIT_INVALID_OUTPUT)
    cost = payload.get("total_cost_usd")
    duration = payload.get("duration_ms")
    return Review(
        summary=structured["summary"],
        findings=_numbered(structured["findings"]),
        model=_model(payload),
        num_turns=int(payload.get("num_turns") or 0),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        duration_s=duration / 1000 if isinstance(duration, (int, float)) else None,
        permission_denials=[
            _denial(d) for d in payload.get("permission_denials") or [] if isinstance(d, dict)
        ],
    )


def _denial(denial: Dict[str, Any]) -> str:
    """`Read /repo/.env`: the refused tool and what it targeted."""
    target = denial.get("tool_input") or {}
    what = next((target[k] for k in ("file_path", "path", "pattern", "command") if target.get(k)), "")
    return f"{denial.get('tool_name', '?')} {what}".strip()


def _raise_on_failure(payload: Dict[str, Any], returncode: int) -> None:
    subtype = payload.get("subtype")
    if subtype in _INCOMPLETE:
        raise DelegateError(_INCOMPLETE[subtype], EXIT_INCOMPLETE)
    if subtype == _OUTPUT_RETRIES_EXHAUSTED:
        raise DelegateError(f"{_INVALID_OUTPUT} (tentatives épuisées)", EXIT_INVALID_OUTPUT)
    if not payload.get("is_error") and subtype == "success" and returncode == 0:
        return
    reason = str(payload.get("result") or subtype or f"code {returncode}")
    if _USAGE_LIMIT.search(reason):
        resets = _RESETS.search(reason)
        when = f" (reprise : {resets.group(1).strip().rstrip('.')})" if resets else ""
        raise DelegateError(f"quota Claude épuisé{when}", EXIT_QUOTA)
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
    usage = payload.get("modelUsage") or {}
    if not usage:
        return "inconnu"
    return str(max(usage, key=lambda name: (usage[name] or {}).get("costUSD", 0)))


def _excerpt(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
