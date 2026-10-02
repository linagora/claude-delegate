"""What the reviewer must never see, whatever the channel: its own reads or the diff."""

from __future__ import annotations

import fnmatch

#: Git-style globs (`**/` matches any depth, including the root).
DENIED_PATHS = ["**/.env", "**/.env.*", "**/.claude/settings*.json"]


def is_denied(path: str) -> bool:
    """Whether a repository-relative path matches one of DENIED_PATHS."""
    for pattern in DENIED_PATHS:
        name = pattern[len("**/") :] if pattern.startswith("**/") else pattern
        if fnmatch.fnmatchcase(path, name) or fnmatch.fnmatchcase(path, f"*/{name}"):
            return True
    return False
