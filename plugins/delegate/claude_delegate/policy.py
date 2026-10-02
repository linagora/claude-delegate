"""What the reviewer must never see, whatever the channel (its own reads or the
diff), nor be configured by."""

from __future__ import annotations

import fnmatch

#: Git-style globs (`**/` matches any depth, including the root).
DENIED_PATHS = ["**/.env", "**/.env.*", "**/.claude/settings*.json"]

#: What configures Claude in a tree: instructions, settings, hooks, MCP
#: servers. A pull request's are stripped before its review.
REVIEWER_CONFIGURATION = {"claude.md", "claude.local.md", ".claude", ".mcp.json"}


def configures_the_reviewer(name: str) -> bool:
    """Whether a file or directory name is in REVIEWER_CONFIGURATION, whatever
    its case: macOS file systems ignore it."""
    return name.lower() in REVIEWER_CONFIGURATION


def is_denied(path: str) -> bool:
    """Whether a repository-relative path matches one of DENIED_PATHS."""
    for pattern in DENIED_PATHS:
        name = pattern[len("**/") :] if pattern.startswith("**/") else pattern
        if fnmatch.fnmatchcase(path, name) or fnmatch.fnmatchcase(path, f"*/{name}"):
            return True
    return False
