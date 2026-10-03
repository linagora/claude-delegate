"""Where the repository is hosted: its origin remote, and the forge that
describes its pull requests."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .errors import EXIT_PREPARATION, DelegateError

#: The only forge supported so far.
GITHUB = "github.com"

#: What gh tells about a pull request.
_FIELDS = ("title", "body", "baseRefName", "headRefOid", "url")


@dataclass(frozen=True)
class Remote:
    host: str
    #: owner/name, without the .git suffix.
    path: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    #: The target branch, such as main.
    base: str
    #: The head commit, as the forge announces it.
    head: str
    url: str
    #: Where git fetches the pull request's head from.
    ref: str


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


def pull_request(origin_url: Optional[str], number: int) -> PullRequest:
    """The pull request as the forge hosting origin describes it."""
    if origin_url is None:
        raise DelegateError(
            "aucun remote origin : impossible de trouver la forge de la pull request", EXIT_PREPARATION
        )
    remote = parse_remote(origin_url)
    if remote is None or remote.host.lower() != GITHUB:
        # Only the host: the URL itself may carry a token.
        where = remote.host if remote else "sans hôte"
        raise DelegateError(
            f"forge non reconnue : origin ({where}) n'est pas sur {GITHUB}, seule forge prise en charge",
            EXIT_PREPARATION,
        )
    what = f"la pull request #{number}"
    data = _query(["pr", "view", str(number), "--repo", f"{GITHUB}/{remote.path}", "--json", ",".join(_FIELDS)], what)
    if not all(isinstance(data.get(field), str) for field in _FIELDS):
        raise _unexpected(what)
    return PullRequest(
        number=number,
        title=data["title"],
        body=data["body"],
        base=data["baseRefName"],
        head=data["headRefOid"],
        url=data["url"],
        ref=f"refs/pull/{number}/head",
    )


def _query(args: List[str], what: str) -> Dict[str, Any]:
    """The JSON object gh prints about `what`."""
    try:
        done = subprocess.run(
            ["gh", *args], capture_output=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL
        )
    except OSError:
        raise DelegateError(
            "gh introuvable : installe GitHub CLI (https://cli.github.com), puis lance gh auth login",
            EXIT_PREPARATION,
        ) from None
    if done.returncode != 0:
        raise DelegateError(f"gh ne peut pas lire {what} : {done.stderr.strip()}", EXIT_PREPARATION)
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise _unexpected(what)
    return data


def _unexpected(what: str) -> DelegateError:
    return DelegateError(f"réponse inattendue de gh pour {what}", EXIT_PREPARATION)
