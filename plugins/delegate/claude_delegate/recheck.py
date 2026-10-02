"""Checking a review again once its findings were addressed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import archive, delegate, gitctx, schemas
from .errors import EXIT_PREPARATION, DelegateError
from .interpret import Finding

#: The findings a recheck rules on, one by one.
RULED_SEVERITIES = ("bloquant", "important")

_REVISION = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_FINDING_ID = re.compile(r"F[1-9][0-9]*")


@dataclass(frozen=True)
class Original:
    """The review a recheck rules on, as its JSON companion records it."""

    id: str
    base: str
    reviewed_revision: str
    requested_model: str
    findings: List[Finding]

    @property
    def ruled(self) -> List[Finding]:
        return [finding for finding in self.findings if finding.severity in RULED_SEVERITIES]

    @property
    def next_number(self) -> int:
        """New findings are numbered after the original ones, so that no two
        findings of a recheck share an identifier."""
        return max((int(finding.id[1:]) for finding in self.findings), default=0) + 1


def original(directory: Path, repo: str, designation: Optional[str]) -> Original:
    """The review to check again: the designated report, else the latest of the
    repository. A recheck stands for its original, so every recheck rules on
    the findings of the review itself."""
    companion = archive.find(directory, designation) if designation else archive.latest(directory)
    if companion is None:
        raise DelegateError(
            "aucun rapport à re-revoir pour ce dépôt : lance d'abord /delegate:hostile-review", EXIT_PREPARATION
        )
    record = archive.load(companion)
    if record.get("type") == "recheck":
        original_id = record.get("original")
        if not isinstance(original_id, str) or not archive.is_report_id(original_id):
            raise DelegateError(f"rapport illisible : {companion}", EXIT_PREPARATION)
        companion = archive.find(companion.parent, original_id)
        record = archive.load(companion)
    if record.get("repo") != repo:
        raise DelegateError(
            f"ce rapport concerne un autre dépôt ({record.get('repo')}), pas {repo}", EXIT_PREPARATION
        )
    if record.get("type") == "pr":
        raise DelegateError("la re-revue d'une pull request n'est pas encore prise en charge", EXIT_PREPARATION)
    return _parse(record, companion)


def reviewer_input(review: Original, ctx: gitctx.RecheckContext) -> str:
    """The findings to rule on, what changed since the review, then the full current diff."""
    lines = [f"Constats de la revue d'origine {review.id} sur lesquels statuer :", ""]
    for finding in review.ruled:
        lines += [
            f"{finding.id} · {finding.severity} · {finding.location}",
            f"Problème : {finding.problem}",
            f"Scénario de défaillance : {finding.failure_scenario}",
            f"Correctif suggéré : {finding.fix}",
            "",
        ]
    if not review.ruled:
        lines += ["(aucun constat bloquant ou important)", ""]
    return (
        "\n".join(lines)
        + "\n--- Début de l'écart, de la révision relue par la revue d'origine jusqu'à l'état courant ---\n"
        + ctx.gap
        + "--- Fin de l'écart ---\n"
        + f"\n--- Début du diff complet courant, depuis le merge-base avec {ctx.base} ---\n"
        + (ctx.diff or "(aucun changement depuis la base)\n")
        + "--- Fin du diff complet courant ---\n"
    )


def _parse(record: Dict[str, Any], companion: Path) -> Original:
    def text(key: str) -> str:
        value = record.get(key)
        return value if isinstance(value, str) else ""

    findings = record.get("findings")
    if (
        record.get("type") != "hostile"
        or not archive.is_report_id(text("id"))
        or not text("base")
        or not _REVISION.fullmatch(text("reviewed_revision"))
        or text("requested_model") not in delegate.MODELS
        or not isinstance(findings, list)
        or not all(_is_recorded_finding(finding) for finding in findings)
    ):
        raise DelegateError(f"rapport illisible : {companion}", EXIT_PREPARATION)
    return Original(
        id=text("id"),
        base=text("base"),
        reviewed_revision=text("reviewed_revision"),
        requested_model=text("requested_model"),
        findings=[
            Finding(
                id=f["id"],
                severity=f["severity"],
                file=f["file"],
                line=f["line"],
                problem=f["problem"],
                failure_scenario=f["failure_scenario"],
                fix=f["fix"],
            )
            for f in findings
        ],
    )


def _is_recorded_finding(value: Any) -> bool:
    return schemas.is_finding(value) and isinstance(value.get("id"), str) and bool(_FINDING_ID.fullmatch(value["id"]))
