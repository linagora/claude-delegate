"""The review report: Markdown rendering."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .interpret import Review

SECTIONS = [("bloquant", "Bloquant"), ("important", "Important"), ("mineur", "Mineur")]


def render(title: str, header: List[Tuple[str, str]], review: Review) -> str:
    lines = [f"# {title}", "", "| Champ | Valeur |", "|---|---|"]
    lines += [f"| {label} | {value} |" for label, value in header]
    lines += ["", "## Résumé", "", review.summary.strip(), ""]
    for severity, name in SECTIONS:
        lines += [f"## {name}", ""]
        findings = [f for f in review.findings if f["severity"] == severity]
        lines += _findings(findings) if findings else ["Rien à signaler.", ""]
    return "\n".join(lines).rstrip() + "\n"


def _findings(findings: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for finding in findings:
        location = finding["file"]
        if finding.get("line") is not None:
            location += f":{finding['line']}"
        lines += [
            f"### {finding['id']} · {location}",
            "",
            f"- **Problème** : {finding['problem']}",
            f"- **Scénario de défaillance** : {finding['failure_scenario']}",
            f"- **Correctif suggéré** : {finding['fix']}",
            "",
        ]
    return lines
