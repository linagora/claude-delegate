"""A fake `claude` for `--dry-run`: it answers the shape of a review, so the
benchmark's plumbing can be checked without calling Anthropic.

It is deliberately outside the plugin and outside the test suite: nothing else
imports it, and `benchmark/compare.py` reaches for it only when `--dry-run` is
given. What it answers is fixed, so a dry run measures nothing about any model —
it only proves the harness builds a repository, runs the CLI and reads a report.
"""

from __future__ import annotations

import json
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

#: One answer per case, chosen so that every path of the scoring is walked:
#: a defect found, a second finding that matches no planted defect, and a clean
#: case the fake leaves alone.
ANSWERS: Dict[str, List[Dict[str, Any]]] = {
    "divide": [
        {
            "severity": "bloquant",
            "file": "totals.py",
            "line": 4,
            "problem": "La division par zéro n'est pas gardée",
            "failure_scenario": "div(1, 0) lève ZeroDivisionError",
            "fix": "Valider le diviseur avant de diviser",
        },
        {
            "severity": "mineur",
            "file": "totals.py",
            "line": 9,
            "problem": "Constat qui ne correspond à aucun défaut planté",
            "failure_scenario": "Inventé pour l'exercice",
            "fix": "Aucun",
        },
    ],
    "pagination": [
        {
            "severity": "important",
            "file": "paging.py",
            "line": 8,
            "problem": "Le reste de la dernière page est perdu",
            "failure_scenario": "page(items, dernier, size) tronque le dernier lot",
            "fix": "Borner la fin à la longueur des éléments",
        }
    ],
    # The clean case: the honest answer is no finding, and the fake gives none.
    "clean": [],
}

#: Reads the case it is answering from the commit the CLI made, then prints a
#: `claude -p --output-format json` result carrying that case's findings.
_SCRIPT = '''#!{python}
import json, subprocess, sys

answers = json.loads({answers!r})
case = subprocess.run(
    ["git", "log", "-1", "--format=%s", "HEAD"], capture_output=True, text=True
).stdout.strip().split(" : ")[0]
review = {{"summary": "Mesure à blanc.", "findings": answers.get(case, [])}}
print(json.dumps({{
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 2,
    "result": json.dumps(review),
    "structured_output": review,
    "total_cost_usd": 0.0,
    "modelUsage": {{"claude-fable-5-1": {{"costUSD": 0.0}}}},
    "permission_denials": [],
    "terminal_reason": "completed",
    "session_id": "benchmark-dry-run",
}}))
'''


def install() -> str:
    """Write a fake `claude` and return its path, to hand to CLAUDE_DELEGATE_BIN."""
    directory = Path(tempfile.mkdtemp(prefix="benchmark-fake-claude-"))
    script = directory / "claude"
    script.write_text(
        _SCRIPT.format(python=sys.executable, answers=json.dumps(ANSWERS)), encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


if __name__ == "__main__":
    print(install())
