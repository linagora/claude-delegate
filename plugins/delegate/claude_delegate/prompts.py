"""The reviewer's system prompts, composed from the plugin's prompt files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

#: ${CLAUDE_PLUGIN_ROOT} is not exported to the shell, so the CLI finds the
#: prompt files from its own location.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def hostile_review(conventions: Optional[str]) -> str:
    return _review_prompt("hostile-review.md", conventions)


def pr_review(conventions: Optional[str]) -> str:
    return _review_prompt("pr-review.md", conventions)


def recheck(conventions: Optional[str], pull_request: bool) -> str:
    """For a pull request, the rules about its tree apply too."""
    return _review_prompt("recheck.md", conventions, omit=() if pull_request else ("pull-request",))


def selftest() -> str:
    return (PROMPTS / "selftest.md").read_text(encoding="utf-8")


def _review_prompt(task_file: str, conventions: Optional[str], omit: Tuple[str, ...] = ()) -> str:
    """A review task, in which reviews share fragments such as the format of
    their findings (but not those in `omit`), followed by the project's trusted
    conventions if any."""
    task = (PROMPTS / task_file).read_text(encoding="utf-8")
    for fragment in ("findings", "security", "pull-request"):
        if fragment in omit:
            task = task.replace(f"{{{fragment}}}\n", "")
        else:
            task = task.replace(f"{{{fragment}}}", (PROMPTS / f"{fragment}.md").read_text(encoding="utf-8").rstrip())
    task = task.rstrip()
    if not conventions:
        return task + "\n"
    # replace, not format: the conventions may contain braces.
    section = (PROMPTS / "conventions.md").read_text(encoding="utf-8").replace("{conventions}", conventions.strip())
    return f"{task}\n\n{section}"
