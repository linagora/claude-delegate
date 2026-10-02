"""The reviewer's system prompts, composed from the plugin's prompt files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

#: ${CLAUDE_PLUGIN_ROOT} is not exported to the shell, so the CLI finds the
#: prompt files from its own location.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def hostile_review(conventions: Optional[str]) -> str:
    """The hostile review task, followed by the project's trusted conventions if any."""
    task = (PROMPTS / "hostile-review.md").read_text(encoding="utf-8").rstrip()
    if not conventions:
        return task + "\n"
    # replace, not format: the conventions may contain braces.
    section = (PROMPTS / "conventions.md").read_text(encoding="utf-8").replace("{conventions}", conventions.strip())
    return f"{task}\n\n{section}"


def selftest() -> str:
    return (PROMPTS / "selftest.md").read_text(encoding="utf-8")
