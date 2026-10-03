"""Where the repository is hosted: its origin remote, and the forge that
describes its pull requests (merge requests on GitLab)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

from .errors import EXIT_PREPARATION, DelegateError


@dataclass(frozen=True)
class Forge:
    """A kind of forge: how it names pull requests, and the CLI that describes them."""

    name: str
    #: What it calls a pull request.
    term: str
    #: What comes before a pull request's number, as in #7 or !7.
    sigil: str
    #: Where git fetches the head of pull request `{number}` from.
    head_ref: str
    #: Its CLI, and how to get it.
    cli: str
    install: str

    def reference(self, number: int) -> str:
        """How it refers to pull request `number`, such as #7 or !7."""
        return f"{self.sigil}{number}"

    def label(self, number: int) -> str:
        """Such as pull request #7 or merge request !7."""
        return f"{self.term} {self.reference(number)}"


GITHUB = Forge(
    name="github",
    term="pull request",
    sigil="#",
    head_ref="refs/pull/{number}/head",
    cli="gh",
    install="installe GitHub CLI (https://cli.github.com), puis lance gh auth login",
)
GITLAB = Forge(
    name="gitlab",
    term="merge request",
    sigil="!",
    head_ref="refs/merge-requests/{number}/head",
    cli="glab",
    install="installe GitLab CLI (https://gitlab.com/gitlab-org/cli), puis lance glab auth login",
)
#: The forges `--forge` may name.
FORGES = {forge.name: forge for forge in (GITHUB, GITLAB)}

#: What gh tells about a pull request.
_GITHUB_FIELDS = ("title", "body", "baseRefName", "headRefOid", "url")
#: What GitLab's REST API tells about a merge request, besides its description.
_GITLAB_FIELDS = ("title", "target_branch", "sha", "web_url")


@dataclass(frozen=True)
class PullRequestKey:
    """Which pull request a chain of reviews follows."""

    forge_name: str
    number: int


@dataclass(frozen=True)
class Remote:
    host: str
    #: The repository's path on its host, such as owner/name or
    #: group/subgroup/name, without the .git suffix.
    path: str


@dataclass(frozen=True)
class PullRequest:
    forge: Forge
    number: int
    title: str
    body: str
    #: The target branch, such as main.
    base: str
    #: The head commit, as the forge announces it.
    head: str
    url: str

    @property
    def ref(self) -> str:
        """Where git fetches the pull request's head from."""
        return self.forge.head_ref.format(number=self.number)

    @property
    def reference(self) -> str:
        return self.forge.reference(self.number)

    @property
    def label(self) -> str:
        return self.forge.label(self.number)


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


def pull_request(origin_url: Optional[str], number: int, forge_name: Optional[str] = None) -> PullRequest:
    """The pull request as the forge hosting origin describes it; `forge_name`
    overrides the forge origin's host points to."""
    remote = _hosted(origin_url)
    forge = FORGES[forge_name] if forge_name else _forge_of(remote.host)
    if forge is GITHUB:
        return _github_pull_request(remote, number)
    return _gitlab_merge_request(remote, number)


def _hosted(origin_url: Optional[str]) -> Remote:
    """origin's remote, which must name a host for its forge to be found."""
    if origin_url is None:
        raise DelegateError(
            "aucun remote origin : impossible de trouver la forge de la pull request", EXIT_PREPARATION
        )
    remote = parse_remote(origin_url)
    if remote is None:
        # Only the host is ever shown: the URL itself may carry a token.
        raise DelegateError("forge introuvable : l'URL d'origin ne nomme aucun hôte", EXIT_PREPARATION)
    return remote


def _forge_of(host: str) -> Forge:
    """GitHub for github.com; GitLab for a host named after it, such as
    gitlab.com, or one glab is logged in to, such as a company instance."""
    host = host.lower()
    if host == "github.com":
        return GITHUB
    if "gitlab" in host:
        return GITLAB
    known = _known_to_glab(host)
    if known:
        return GITLAB
    unknown = f"forge non reconnue pour origin ({host}) : précise-la avec --forge github ou --forge gitlab"
    if known is None:
        unknown += f". Sans glab, une instance GitLab ne peut pas être reconnue : {GITLAB.install}"
    raise DelegateError(unknown, EXIT_PREPARATION)


def _known_to_glab(host: str) -> Optional[bool]:
    """Whether glab is logged in to `host`; None when glab is not installed."""
    try:
        done = subprocess.run(
            [GITLAB.cli, "auth", "status", "--hostname", host],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def _github_pull_request(remote: Remote, number: int) -> PullRequest:
    what = f"la {GITHUB.label(number)}"
    repository = f"{remote.host.lower()}/{remote.path}"
    fields = ",".join(_GITHUB_FIELDS)
    data = _query(GITHUB, ["pr", "view", str(number), "--repo", repository, "--json", fields], what)
    if not all(isinstance(data.get(field), str) for field in _GITHUB_FIELDS):
        raise _unexpected(GITHUB, what)
    return PullRequest(
        forge=GITHUB,
        number=number,
        title=data["title"],
        body=data["body"],
        base=data["baseRefName"],
        head=data["headRefOid"],
        url=data["url"],
    )


def _gitlab_merge_request(remote: Remote, number: int) -> PullRequest:
    what = f"la {GITLAB.label(number)}"
    endpoint = f"projects/{quote(remote.path, safe='')}/merge_requests/{number}"
    data = _query(GITLAB, ["api", "--hostname", remote.host.lower(), endpoint], what)
    # GitLab gives null for a merge request without description.
    description = data.get("description") or ""
    if not all(isinstance(data.get(field), str) for field in _GITLAB_FIELDS) or not isinstance(description, str):
        raise _unexpected(GITLAB, what)
    return PullRequest(
        forge=GITLAB,
        number=number,
        title=data["title"],
        body=description,
        base=data["target_branch"],
        head=data["sha"],
        url=data["web_url"],
    )


def _query(forge: Forge, args: List[str], what: str) -> Dict[str, Any]:
    """The JSON object the forge's CLI prints about `what`."""
    try:
        done = subprocess.run(
            [forge.cli, *args], capture_output=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL
        )
    except OSError:
        raise DelegateError(f"{forge.cli} introuvable : {forge.install}", EXIT_PREPARATION) from None
    if done.returncode != 0:
        raise DelegateError(f"{forge.cli} ne peut pas lire {what} : {done.stderr.strip()}", EXIT_PREPARATION)
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise _unexpected(forge, what)
    return data


def _unexpected(forge: Forge, what: str) -> DelegateError:
    return DelegateError(f"réponse inattendue de {forge.cli} pour {what}", EXIT_PREPARATION)
