"""Reading the delegated session's result: failures, schema validation, numbering."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List

from . import schemas
from .errors import DelegateError


@dataclass(frozen=True)
class Review:
    summary: str
    findings: List[Dict[str, Any]]
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


def _numbered(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Most severe first (model order kept within a severity), numbered F1, F2…"""
    ordered = sorted(findings, key=lambda f: schemas.SEVERITIES.index(f["severity"]))
    fields = schemas.FINDING["required"]
    return [
        {"id": f"F{n}", **{field: finding[field] for field in fields}}
        for n, finding in enumerate(ordered, start=1)
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
