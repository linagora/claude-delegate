"""Where the repository is hosted: its origin remote."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Remote:
    host: str
    #: owner/name, without the .git suffix.
    path: str


def parse_remote(url: str) -> Optional[Remote]:
    """Host and repository path of a remote URL, scp-like (git@host:owner/name)
    or not; None for a URL without both, such as a local path."""
    scp_like = re.match(r"^(?:[^@/]+@)?([^:/]+):(?!//)(.+)$", url)
    if scp_like and "://" not in url:
        host, path = scp_like.group(1), scp_like.group(2)
    else:
        parts = urlsplit(url)  # .hostname drops any user:token@ prefix
        host, path = parts.hostname or "", parts.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not host or not path:
        return None
    return Remote(host, path)
