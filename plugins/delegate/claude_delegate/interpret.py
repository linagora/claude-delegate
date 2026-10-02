"""Reading the delegated session's result: failures, schema validation, numbering."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import schemas
from .errors import DelegateError


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


def read_review(done: "subprocess.CompletedProcess[str]") -> Review:
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
