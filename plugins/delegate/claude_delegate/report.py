"""The review report: one record, rendered as Markdown and as its JSON companion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .delegate import Execution
from .gitctx import HostileContext, PullRequestContext, RecheckContext
from .interpret import Finding, Review, Status
from .schemas import SEVERITIES


#: Report kinds, as their JSON companion records them.
HOSTILE, PULL_REQUEST, RECHECK = "hostile", "pr", "recheck"


@dataclass(frozen=True)
class Subject:
    """What a report is about: its kind and title, and its own header rows and
    companion fields."""

    kind: str
    #: Names the subject in report identifiers, such as hostile or pr-7.
    slug: str
    title: str
    rows: List[Tuple[str, str]]
    fields: Dict[str, Any]


def hostile_subject(ctx: HostileContext) -> Subject:
    return Subject(
        kind=HOSTILE,
        slug=HOSTILE,
        title="Revue hostile",
        rows=[
            _base_row(ctx.base, ctx.merge_base),
            ("Révision relue", _short(ctx.reviewed_revision)),
        ],
        fields={
            "base": ctx.base,
            "merge_base": ctx.merge_base,
            "reviewed_revision": ctx.reviewed_revision,
        },
    )


def pr_subject(ctx: PullRequestContext) -> Subject:
    pr = ctx.pull_request
    return Subject(
        kind=PULL_REQUEST,
        slug=f"{PULL_REQUEST}-{pr.number}",
        title="Revue de pull request",
        rows=[
            ("Pull request", f"#{pr.number} {pr.url}"),
            ("Branche cible", pr.base),
            # In full: DeepSeek reads the reviewed files at this commit.
            ("Tête", pr.head),
            ("Fichiers non relus", ", ".join(ctx.unreviewed) or "aucun"),
        ],
        fields={
            "pr_number": pr.number,
            "url": pr.url,
            "base": pr.base,
            "base_revision": ctx.base_revision,
            "merge_base": ctx.merge_base,
            "head": pr.head,
            "unreviewed_files": ctx.unreviewed,
        },
    )


def recheck_subject(original_id: str, ctx: RecheckContext) -> Subject:
    return Subject(
        kind=RECHECK,
        slug=RECHECK,
        title="Re-revue",
        rows=[
            ("Revue d'origine", original_id),
            _base_row(ctx.base, ctx.merge_base),
            ("Révision d'origine", _short(ctx.original_revision)),
            ("Révision relue", _short(ctx.reviewed_revision)),
        ],
        fields={
            "original": original_id,
            "base": ctx.base,
            "merge_base": ctx.merge_base,
            "original_revision": ctx.original_revision,
            "reviewed_revision": ctx.reviewed_revision,
        },
    )


@dataclass(frozen=True)
class Report:
    id: str
    created_at: datetime
    repo: str
    subject: Subject
    execution: Execution
    review: Review

    def markdown(self) -> str:
        return _render(self.subject.title, self._header(), self.review)

    def companion(self) -> Dict[str, Any]:
        verdict, statuses = self.review.verdict, self.review.statuses
        return {
            "id": self.id,
            "type": self.subject.kind,
            "created_at": self.created_at.isoformat(),
            "repo": self.repo,
            **self.subject.fields,
            "requested_model": self.execution.requested_model,
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
            **({"verdict": verdict.decision, "verdict_reason": verdict.reason} if verdict else {}),
            **({"statuses": [_status_record(status) for status in statuses]} if statuses is not None else {}),
            "findings": [asdict(finding) for finding in self.review.findings],
        }

    def _header(self) -> List[Tuple[str, str]]:
        return [
            ("Identifiant", self.id),
            ("Type", self.subject.title.lower()),
            ("Date (UTC)", f"{self.created_at:%Y-%m-%d %H:%M:%S}"),
            ("Dépôt", self.repo),
            *self.subject.rows,
            ("Modèle", self.review.model),
            ("Effort", self.execution.effort),
            ("Tours", _unknown_if_none(self.review.num_turns, "inconnu")),
            ("Coût estimé", _money(self.review.cost_usd)),
            ("Durée", _duration(self.review.duration_s)),
            ("Prompt", _short(self.execution.prompt_sha256)),
            ("Versions", _versions(self.execution.claude_code_version)),
            ("Permissions refusées", _denials(self.review.permission_denials)),
        ]


def _cell(text: str) -> str:
    """Keep a value inside its Markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def _base_row(base: str, merge_base: str) -> Tuple[str, str]:
    return ("Base", f"{base} (merge-base {_short(merge_base)})")


def _short(digest: str) -> str:
    """Abbreviated commit id or hash, as shown in report headers."""
    return digest[:12]


def _versions(claude_code: Optional[str]) -> str:
    return f"claude-delegate {__version__}, Claude Code {claude_code or 'inconnue'}"


def _unknown_if_none(value: Optional[int], unknown: str) -> str:
    return unknown if value is None else str(value)


#: Beyond this, the header only counts the remaining denials (the companion keeps them all).
_SHOWN_DENIALS = 10


def _denials(denials: Optional[List[str]]) -> str:
    if denials is None:
        return "inconnues"
    shown = "; ".join(denials[:_SHOWN_DENIALS]) or "aucune"
    hidden = len(denials) - _SHOWN_DENIALS
    return f"{shown} (+{hidden} autres)" if hidden > 0 else shown


def _money(usd: Optional[float]) -> str:
    return "inconnu" if usd is None else f"{usd:.2f} $".replace(".", ",")


def _duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "inconnue"
    total = round(seconds)
    return f"{total} s" if total < 60 else f"{total // 60} min {total % 60:02d} s"


def _render(title: str, header: List[Tuple[str, str]], review: Review) -> str:
    lines = [f"# {title}", "", "| Champ | Valeur |", "|---|---|"]
    lines += [f"| {_cell(label)} | {_cell(value)} |" for label, value in header]
    lines += ["", "## Résumé", "", review.summary.strip(), ""]
    if review.verdict:
        lines += ["## Verdict", "", f"{review.verdict.decision} : {review.verdict.reason.strip()}", ""]
    if review.statuses is not None:
        lines += ["## Constats d'origine", ""] + _statuses(review.statuses)
    for severity in SEVERITIES:
        lines += [f"## {severity.capitalize()}", ""]
        findings = [f for f in review.findings if f.severity == severity]
        lines += _findings(findings) if findings else ["Rien à signaler.", ""]
    return "\n".join(lines).rstrip() + "\n"


def _statuses(statuses: List[Status]) -> List[str]:
    """Each ruling, with what the original finding was, so that it can be checked."""
    lines: List[str] = []
    for status in statuses:
        finding = status.finding
        lines += [
            f"### {finding.id} · {finding.location} ({finding.severity}) : {status.status}",
            "",
            f"- **Problème** : {finding.problem}",
            f"- **Justification** : {status.justification.strip()}",
            "",
        ]
    return lines or ["Aucun constat bloquant ou important à vérifier.", ""]


def _status_record(status: Status) -> Dict[str, str]:
    return {"id": status.finding.id, "status": status.status, "justification": status.justification}


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
