"""The reviewer's system prompts, composed from the plugin's prompt files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

#: ${CLAUDE_PLUGIN_ROOT} is not exported to the shell, so the CLI finds the
#: prompt files from its own location.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

CONVENTIONS_HEADING = "## Conventions du projet (version de confiance)"


def hostile_review(conventions: Optional[str]) -> str:
    """The hostile review task, followed by the project's trusted conventions if any."""
    task = (PROMPTS / "hostile-review.md").read_text(encoding="utf-8").rstrip()
    if not conventions or not conventions.strip():
        return task + "\n"
    return (
        f"{task}\n\n{CONVENTIONS_HEADING}\n\n"
        "Ces conventions viennent de la révision de base du dépôt, pas des changements relus : "
        "vérifie que les changements les respectent.\n\n"
        f"{conventions.strip()}\n"
    )
