"""The review report: one record, rendered as Markdown and as its JSON companion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .delegate import Execution
from .gitctx import HostileContext
from .interpret import Finding, Review
from .schemas import SEVERITIES


@dataclass(frozen=True)
class HostileReport:
    id: str
    created_at: datetime
    repo: str
    context: HostileContext
    execution: Execution
    review: Review

    def markdown(self) -> str:
        return _render("Revue hostile", self._header(), self.review)

    def companion(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "hostile",
            "created_at": self.created_at.isoformat(),
            "repo": self.repo,
            "base": self.context.base,
            "merge_base": self.context.merge_base,
            "reviewed_revision": self.context.reviewed_revision,
            "requested_model": self.execution.model,
            "model": self.review.model,
            "effort": self.execution.effort,
            "num_turns": self.review.num_turns,
            "cost_usd": self.review.cost_usd,
            "duration_s": self.review.duration_s,
            "prompt_sha256": self.execution.prompt_sha256,
            "plugin_version": __version__,
            "claude_code_version": self.execution.claude_code_version,
            "permission_denials": self.review.permission_denials,
            "summary": self.review.summary,
            "findings": [asdict(finding) for finding in self.review.findings],
        }

    def _header(self) -> List[Tuple[str, str]]:
        return [
            ("Identifiant", self.id),
            ("Type", "revue hostile"),
            ("Date (UTC)", f"{self.created_at:%Y-%m-%d %H:%M:%S}"),
            ("Dépôt", self.repo),
            ("Base", f"{self.context.base} (merge-base {_short(self.context.merge_base)})"),
            ("Révision relue", _short(self.context.reviewed_revision)),
            ("Modèle", self.review.model),
            ("Effort", self.execution.effort),
            ("Tours", _unknown_if_none(self.review.num_turns, "inconnu")),
            ("Coût estimé", _money(self.review.cost_usd)),
            ("Durée", _duration(self.review.duration_s)),
            ("Prompt", _short(self.execution.prompt_sha256)),
            ("Versions", f"claude-delegate {__version__}, Claude Code {self.execution.claude_code_version or 'inconnue'}"),
            ("Permissions refusées", _denials(self.review.permission_denials)),
        ]


def _short(digest: str) -> str:
    """Abbreviated commit id or hash, as shown in report headers."""
    return digest[:12]


def _unknown_if_none(value: Optional[int], unknown: str) -> str:
    return unknown if value is None else str(value)


def _denials(denials: Optional[List[str]]) -> str:
    if denials is None:
        return "inconnues"
    return "; ".join(denials) or "aucune"


def _money(usd: Optional[float]) -> str:
    return "inconnu" if usd is None else f"{usd:.2f} $".replace(".", ",")


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "inconnue"
    total = round(seconds)
    return f"{total} s" if total < 60 else f"{total // 60} min {total % 60:02d} s"


def _render(title: str, header: List[Tuple[str, str]], review: Review) -> str:
    lines = [f"# {title}", "", "| Champ | Valeur |", "|---|---|"]
    lines += [f"| {label} | {value} |" for label, value in header]
    lines += ["", "## Résumé", "", review.summary.strip(), ""]
    for severity in SEVERITIES:
        lines += [f"## {severity.capitalize()}", ""]
        findings = [f for f in review.findings if f.severity == severity]
        lines += _findings(findings) if findings else ["Rien à signaler.", ""]
    return "\n".join(lines).rstrip() + "\n"


def _findings(findings: List[Finding]) -> List[str]:
    lines: List[str] = []
    for finding in findings:
        lines += [
            f"### {finding.id} · {finding.location}",
            "",
            f"- **Problème** : {finding.problem}",
            f"- **Scénario de défaillance** : {finding.failure_scenario}",
            f"- **Correctif suggéré** : {finding.fix}",
            "",
        ]
    return lines
