"""What the reviewer must never see, whatever the channel: its own reads or the diff."""

from __future__ import annotations

#: Git-style globs (`**/` matches any depth, including the root).
DENIED_PATHS = ["**/.env", "**/.env.*", "**/.claude/settings*.json"]
