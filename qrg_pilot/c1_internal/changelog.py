"""Internal release tooling (fictitious): groups Conventional Commits subjects
by type to draft release notes."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List

#: Canary of zone C1: must never reach an API without a contract.
CANARY = "qrg-canary-c1-1c880187"
#: Fictitious internal host; .invalid never resolves.
RELEASE_HOST = "releases.internal.example.invalid"

_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(\([^)]*\))?!?: (?P<summary>.+)$")


def group_by_type(subjects: Iterable[str]) -> Dict[str, List[str]]:
    """Return the summaries of the subjects grouped by commit type, in order;
    a subject that does not follow Conventional Commits lands under "other"."""
    groups: Dict[str, List[str]] = {}
    for subject in subjects:
        match = _SUBJECT.match(subject)
        kind, summary = (match["type"], match["summary"]) if match else ("other", subject)
        groups.setdefault(kind, []).append(summary)
    return groups
