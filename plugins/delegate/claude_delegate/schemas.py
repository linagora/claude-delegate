"""The structured-output contract with the delegated reviewer (passed via --json-schema).

Finding identifiers are not part of a finding: the model would invent its
own, so the CLI numbers findings itself (F1, F2…). A recheck then rules on
findings under these identifiers.
"""

from __future__ import annotations

from typing import Any, Dict, List

SEVERITIES = ["bloquant", "important", "mineur"]

FINDING: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": SEVERITIES},
        "file": {"type": "string"},
        "line": {"type": ["integer", "null"]},
        "problem": {"type": "string"},
        "failure_scenario": {"type": "string"},
        "fix": {"type": "string"},
    },
    "required": ["severity", "file", "line", "problem", "failure_scenario", "fix"],
}

HOSTILE_REVIEW: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": FINDING},
    },
    "required": ["summary", "findings"],
}

VERDICTS = ["APPROVE", "REQUEST_CHANGES"]

PR_REVIEW: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "verdict": {"type": "string", "enum": VERDICTS},
        "verdict_reason": {"type": "string"},
        "findings": {"type": "array", "items": FINDING},
    },
    "required": ["summary", "verdict", "verdict_reason", "findings"],
}

#: How a recheck rules on an original finding.
STATUSES = ["traité", "non traité", "mal traité"]

_STATUS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": STATUSES},
        "justification": {"type": "string"},
    },
    "required": ["status", "justification"],
}


def recheck(ids: List[str]) -> Dict[str, Any]:
    """A ruling on each of these original findings, keyed by identifier so that
    none can be skipped, then the new findings."""
    statuses: Dict[str, Any] = {
        "type": "object",
        "properties": {finding: _STATUS for finding in ids},
        "additionalProperties": False,
    }
    if ids:
        statuses["required"] = list(ids)
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "statuses": statuses,
            "findings": {"type": "array", "items": FINDING},
        },
        "required": ["summary", "statuses", "findings"],
    }


#: What the selftest's reviewer reports: what it could read, and the project
#: codeword it believes its instructions give.
SELFTEST: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "outside_file": {"type": ["string", "null"]},
        "env_file": {"type": ["string", "null"]},
        "codeword": {"type": ["string", "null"]},
        "tools": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["outside_file", "env_file", "codeword", "tools"],
}


def is_review(value: Any) -> bool:
    """Whether a structured output honours HOSTILE_REVIEW."""
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        return False
    findings = value.get("findings")
    return isinstance(findings, list) and all(is_finding(f) for f in findings)


def is_pr_review(value: Any) -> bool:
    """Whether a structured output honours PR_REVIEW."""
    return (
        is_review(value)
        and value.get("verdict") in VERDICTS
        and isinstance(value.get("verdict_reason"), str)
    )


def is_recheck(value: Any, ids: List[str]) -> bool:
    """Whether a structured output honours recheck(ids)."""
    if not is_review(value):
        return False
    statuses = value.get("statuses")
    return isinstance(statuses, dict) and set(statuses) == set(ids) and all(map(_is_status, statuses.values()))


def is_finding(value: Any) -> bool:
    """Whether a value honours FINDING."""
    if not isinstance(value, dict) or value.get("severity") not in SEVERITIES or "line" not in value:
        return False
    line = value["line"]
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        return False
    return all(isinstance(value.get(key), str) for key in ("file", "problem", "failure_scenario", "fix"))


def _is_status(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") in STATUSES
        and isinstance(value.get("justification"), str)
    )
