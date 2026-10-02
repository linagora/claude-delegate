"""The structured-output contract with the delegated reviewer (passed via --json-schema).

Finding identifiers are not part of the contract: the model invents its own,
so the CLI numbers findings itself (F1, F2…).
"""

from __future__ import annotations

from typing import Any, Dict

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


def is_review(value: Any) -> bool:
    """Whether a structured output honours HOSTILE_REVIEW."""
    if not isinstance(value, dict) or not isinstance(value.get("summary"), str):
        return False
    findings = value.get("findings")
    return isinstance(findings, list) and all(_is_finding(f) for f in findings)


def _is_finding(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("severity") not in SEVERITIES:
        return False
    line = value.get("line")
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        return False
    return all(isinstance(value.get(key), str) for key in ("file", "problem", "failure_scenario", "fix"))
