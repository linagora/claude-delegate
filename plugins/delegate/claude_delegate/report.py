"""The review report: one record, rendered as Markdown and as its JSON companion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .interpret import Finding, Review
from .schemas import SEVERITIES


@dataclass(frozen=True)
class HostileReport:
    id: str
    created_at: datetime
    repo: str
    base: str
    merge_base: str
    review: Review

    def markdown(self) -> str:
        return _render("Revue hostile", self._header(), self.review)

    def companion(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "hostile",
            "created_at": self.created_at.isoformat(),
            "repo": self.repo,
            "base": self.base,
            "merge_base": self.merge_base,
            "model": self.review.model,
            "summary": self.review.summary,
            "findings": [asdict(finding) for finding in self.review.findings],
        }

    def _header(self) -> List[Tuple[str, str]]:
        return [
            ("Identifiant", self.id),
            ("Date (UTC)", f"{self.created_at:%Y-%m-%d %H:%M:%S}"),
            ("Dépôt", self.repo),
            ("Base", f"{self.base} (merge-base {self.merge_base[:12]})"),
            ("Modèle", self.review.model),
        ]


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
