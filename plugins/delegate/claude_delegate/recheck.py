"""Checking a report again once its findings were addressed.

A recheck rules on what the report it checks left open: the blocking and
important findings of a review, or, for an earlier recheck, the findings it
did not find fixed and those it found. Rechecks thus follow the fixes one
after another, numbering every new finding after the last. For a pull
request, each recheck reads its new head, asked of its forge again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import archive, delegate, forge, gitctx, report, schemas
from .errors import EXIT_PREPARATION, DelegateError
from .interpret import Finding, Status

#: The findings a recheck rules on, one by one.
_RULED_SEVERITIES = ("bloquant", "important")
#: A finding ruled so is closed: later rechecks no longer rule on it.
_FIXED = "traité"

_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FINDING_ID = re.compile(r"F[1-9][0-9]*")


@dataclass(frozen=True)
class ReportToRecheck:
    """A review or an earlier recheck, as its JSON companion records it."""

    id: str
    base: str
    #: What the report read: a frozen working tree, or a pull request's head.
    reviewed_revision: str
    requested_model: str
    #: What the recheck rules on, oldest first.
    open_findings: List[Finding]
    #: The last ruling on an open finding, when an earlier recheck made one.
    last_rulings: Dict[str, Status]
    #: New findings are numbered from here, after every finding before them.
    next_number: int
    #: The pull request the reports follow; None after a hostile review.
    pull_request: Optional[forge.PullRequestKey] = None


def report_to_recheck(repo: str, designation: Optional[str]) -> ReportToRecheck:
    """The designated report of the repository, else its latest one."""
    directory = archive.state_dir() / repo
    companion = archive.find(directory, designation) if designation else archive.latest(directory)
    if companion is None:
        raise DelegateError(
            "aucun rapport à re-revoir pour ce dépôt : lance d'abord /delegate:hostile-review", EXIT_PREPARATION
        )
    record = archive.load(companion)
    if record.get("repo") != repo:
        raise DelegateError(
            f"ce rapport concerne un autre dépôt ({record.get('repo')}), pas {repo}", EXIT_PREPARATION
        )
    return _parse(record, companion)


def reviewer_input(earlier: ReportToRecheck, ctx: gitctx.RecheckContext) -> str:
    """The pull request if any, the findings to rule on, what changed since the
    report, then the full current diff."""
    header = gitctx.pull_request_header(ctx.pull_request, ctx.unreviewed) + "\n" if ctx.pull_request else ""
    lines = [f"Constats du rapport {earlier.id} sur lesquels statuer :", ""]
    for finding in earlier.open_findings:
        lines += [
            f"{finding.id} · {finding.severity} · {finding.location}",
            f"Problème : {finding.problem}",
            f"Scénario de défaillance : {finding.failure_scenario}",
            f"Correctif suggéré : {finding.fix}",
        ]
        last = earlier.last_rulings.get(finding.id)
        if last:
            lines.append(f"Dernier statut : {last.status}. {last.justification}")
        lines.append("")
    if not earlier.open_findings:
        lines += ["(aucun constat bloquant ou important ouvert)", ""]
    return (
        header
        + "\n".join(lines)
        + "\n--- Début de l'écart, de la révision relue par ce rapport jusqu'à l'état courant ---\n"
        + ctx.gap
        + "--- Fin de l'écart ---\n"
        + f"\n--- Début du diff complet courant, depuis le merge-base avec {ctx.base} ---\n"
        + (ctx.diff or "(aucun changement depuis la base)\n")
        + "--- Fin du diff complet courant ---\n"
    )


def _parse(record: Dict[str, Any], companion: Path) -> ReportToRecheck:
    def text(key: str) -> str:
        value = record.get(key)
        return value if isinstance(value, str) else ""

    kind = record.get("type")
    findings = _findings(record.get("findings"))
    rulings: Optional[List[Status]] = None
    revision = text("reviewed_revision")
    if kind in (report.HOSTILE, report.PULL_REQUEST):
        rulings = []
    elif kind == report.RECHECK:
        rulings = _rulings(record.get("statuses"))
    if kind == report.PULL_REQUEST:
        revision = text("head")
    if (
        findings is None
        or rulings is None
        or not archive.is_report_id(text("id"))
        or not text("base")
        or not _REVISION.fullmatch(revision)
        or text("requested_model") not in delegate.MODELS
    ):
        raise _unreadable(companion)
    # A pull request review names its pull request, and so do its rechecks.
    pull_request = _pull_request(record, companion) if "pr_number" in record or kind == report.PULL_REQUEST else None
    last = max((int(f.id[1:]) for f in findings + [ruling.finding for ruling in rulings]), default=0)
    # A recheck records it: findings dropped from the chain keep their number.
    next_number = record.get("next_finding_number") if kind == report.RECHECK else last + 1
    if not isinstance(next_number, int) or isinstance(next_number, bool) or next_number <= last:
        raise _unreadable(companion)
    unresolved = [ruling for ruling in rulings if ruling.status != _FIXED]
    return ReportToRecheck(
        id=text("id"),
        base=text("base"),
        reviewed_revision=revision,
        requested_model=text("requested_model"),
        open_findings=[ruling.finding for ruling in unresolved]
        + [finding for finding in findings if finding.severity in _RULED_SEVERITIES],
        last_rulings={ruling.finding.id: ruling for ruling in unresolved},
        next_number=next_number,
        pull_request=pull_request,
    )


def _pull_request(record: Dict[str, Any], companion: Path) -> forge.PullRequestKey:
    # Pull request reviews recorded no forge before GitLab support: GitHub.
    forge_name = record.get("forge", forge.GITHUB.name)
    number = record.get("pr_number")
    if (
        not isinstance(forge_name, str)
        or forge_name not in forge.FORGES
        or not isinstance(number, int)
        or isinstance(number, bool)
        or number < 1
    ):
        raise _unreadable(companion)
    return forge.PullRequestKey(forge_name, number)


def _unreadable(companion: Path) -> DelegateError:
    return DelegateError(f"rapport illisible : {companion}", EXIT_PREPARATION)


def _findings(value: Any) -> Optional[List[Finding]]:
    """Findings as a report records them, or None when they are malformed."""
    if not isinstance(value, list) or not all(map(_is_recorded_finding, value)):
        return None
    return [Finding.from_record(finding, finding["id"]) for finding in value]


def _rulings(value: Any) -> Optional[List[Status]]:
    """A recheck's rulings as its report records them, or None when they are malformed."""
    findings = _findings(value)
    if findings is None or not all(
        ruling.get("status") in schemas.STATUSES and isinstance(ruling.get("justification"), str) for ruling in value
    ):
        return None
    return [Status(finding, ruling["status"], ruling["justification"]) for finding, ruling in zip(findings, value)]


def _is_recorded_finding(value: Any) -> bool:
    return schemas.is_finding(value) and isinstance(value.get("id"), str) and bool(_FINDING_ID.fullmatch(value["id"]))
