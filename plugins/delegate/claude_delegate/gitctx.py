"""What the reviewer reads: the diff to review, prepared from git."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from . import conventions, forge, policy
from .errors import EXIT_PREPARATION, DelegateError

#: Denied files stay out of the diff too, since the reviewer may not read them.
_DENIED = [f":(exclude,glob){path}" for path in policy.DENIED_PATHS]

#: Beyond this (about 250k tokens), a review costs too much to be useful.
MAX_DIFF_CHARS = 1_000_000

#: What a pull request could bring to steer its reviewer: instructions,
#: settings, hooks, MCP servers. Matched whatever the case, as macOS does.
_REVIEWER_CONFIGURATION = {"claude.md", "claude.local.md", ".claude", ".mcp.json"}

#: Identity of the technical commit that freezes the reviewed revision, so that
#: building it never depends on the user's git configuration.
_TECHNICAL_IDENTITY = {
    "GIT_AUTHOR_NAME": "claude-delegate",
    "GIT_AUTHOR_EMAIL": "claude-delegate@localhost",
    "GIT_COMMITTER_NAME": "claude-delegate",
    "GIT_COMMITTER_EMAIL": "claude-delegate@localhost",
}


@dataclass(frozen=True)
class HostileContext:
    root: Path
    origin_url: Optional[str]
    base: str
    merge_base: str
    reviewed_revision: str
    diff: str
    #: The root CLAUDE.md at the merge-base, never from the reviewed work.
    conventions: Optional[str]


@dataclass(frozen=True)
class PullRequestContext:
    root: Path
    origin_url: Optional[str]
    pull_request: forge.PullRequest
    #: The tip of the target branch, fetched for the review.
    base_revision: str
    merge_base: str
    diff: str
    #: The root CLAUDE.md of the target branch, never from the pull request.
    conventions: Optional[str]

    def reviewer_input(self) -> str:
        """The pull request as its author presents it, then its diff."""
        pr = self.pull_request
        return (
            f"Pull request #{pr.number} : {pr.title}\n"
            f"URL : {pr.url}\n"
            f"Branche cible : {pr.base}\n"
            f"Tête : {pr.head}\n"
            "\n--- Début de la description de la pull request ---\n"
            f"{pr.body.strip() or '(aucune description)'}\n"
            "--- Fin de la description de la pull request ---\n"
            f"\n--- Début du diff, du merge-base avec {pr.base} jusqu'à la tête ---\n"
            f"{self.diff}"
            "--- Fin du diff ---\n"
        )


def hostile_context(cwd: Path, base: Optional[str]) -> HostileContext:
    root = _repository(cwd)
    if _git_or_none(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}") is None:
        raise DelegateError("le dépôt n'a encore aucun commit", EXIT_PREPARATION)
    base = base or default_base(root)
    if _git_or_none(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}") is None:
        raise DelegateError(f"base introuvable : {base}", EXIT_PREPARATION)
    merge_base = _git_or_none(root, "merge-base", base, "HEAD")
    if merge_base is None:
        raise DelegateError(f"aucun ancêtre commun entre {base} et HEAD", EXIT_PREPARATION)
    conventions_text = trusted_conventions(root, merge_base)
    reviewed_revision = _freeze_working_tree(root)
    return HostileContext(
        root=root,
        origin_url=origin_url(root),
        base=base,
        merge_base=merge_base,
        reviewed_revision=reviewed_revision,
        diff=_reviewable_diff(root, merge_base, reviewed_revision, f"aucun changement depuis {base}"),
        conventions=conventions_text,
    )


def pull_request_context(cwd: Path, number: int) -> PullRequestContext:
    root = _repository(cwd)
    origin = origin_url(root)
    pr = forge.pull_request(origin, number)
    tracking = f"refs/remotes/origin/{pr.base}"
    base_revision = _fetch(root, f"+refs/heads/{pr.base}:{tracking}", tracking)
    head = _fetch(root, pr.ref, "FETCH_HEAD")
    if head != pr.head:
        raise DelegateError(
            f"la pull request #{number} a changé pendant la préparation (tête {pr.head[:12]} selon la forge, "
            f"{head[:12]} récupérée) : relance la revue",
            EXIT_PREPARATION,
        )
    merge_base = _git_or_none(root, "merge-base", base_revision, head)
    if merge_base is None:
        raise DelegateError(f"aucun ancêtre commun entre {pr.base} et la pull request #{number}", EXIT_PREPARATION)
    return PullRequestContext(
        root=root,
        origin_url=origin,
        pull_request=pr,
        base_revision=base_revision,
        merge_base=merge_base,
        diff=_reviewable_diff(root, merge_base, head, f"la pull request #{number} ne change rien à {pr.base}"),
        conventions=trusted_conventions(root, base_revision),
    )


@contextmanager
def pull_request_worktree(root: Path, head: str) -> Iterator[Path]:
    """`head` checked out in a detached, throwaway worktree outside the
    repository, stripped of the configuration the pull request brings. The
    worktree is removed whatever happens, interruptions included."""
    with tempfile.TemporaryDirectory(prefix="claude-delegate-pr-") as tmp:
        tree = Path(tmp).resolve() / "pull-request"
        try:
            # No hooks: a post-checkout hook runs inside the new worktree, where
            # it could run the pull request's own code (npm install, lefthook…).
            git(root, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", str(tree), head)
            _strip_reviewer_configuration(tree)
            yield tree
        finally:
            _run(root, ("worktree", "remove", "--force", str(tree)))


def trusted_conventions(root: Path, revision: str) -> Optional[str]:
    """The conventions as they are at `revision`, so the reviewed work cannot change them."""
    return conventions.trusted(lambda path: _entry(root, revision, path))


def default_base(root: Path) -> str:
    """The default branch of origin (origin/HEAD), else main."""
    return _git_or_none(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "main"


def origin_url(root: Path) -> Optional[str]:
    """origin's URL as configured: unlike `git remote get-url`, before any
    insteadOf rule rewrites it to a mirror or a local path."""
    urls = _git_or_none(root, "config", "--get-all", "remote.origin.url")
    return urls.splitlines()[0] if urls else None


def git(cwd: Path, *args: str, strip: bool = True, env: Optional[Dict[str, str]] = None) -> str:
    """A git command the review cannot do without: its failure is reported."""
    done = _run(cwd, args, env)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}", EXIT_PREPARATION)
    return done.stdout.strip() if strip else done.stdout


def _repository(cwd: Path) -> Path:
    """The root of the repository holding `cwd`."""
    toplevel = _git_or_none(cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        raise DelegateError(f"pas un dépôt git : {cwd}", EXIT_PREPARATION)
    return Path(toplevel)


def _reviewable_diff(root: Path, start: str, end: str, unchanged: str) -> str:
    """The diff from `start` to `end` that the reviewer receives, without denied
    files; `unchanged` says why there is nothing to review when it is empty."""
    diff = git(root, "diff", "--no-color", "--no-ext-diff", start, end, "--", ".", *_DENIED, strip=False)
    if not diff.strip():
        raise DelegateError(f"rien à relire : {unchanged}", EXIT_PREPARATION)
    if len(diff) > MAX_DIFF_CHARS:
        size, limit = (f"{n:,}".replace(",", " ") for n in (len(diff), MAX_DIFF_CHARS))
        raise DelegateError(
            f"diff trop volumineux pour une revue : {size} caractères (maximum {limit})", EXIT_PREPARATION
        )
    return diff


def _fetch(root: Path, refspec: str, fetched: str) -> str:
    """Fetch `refspec` from origin; returns the commit `fetched` then names."""
    no_prompt = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    git(root, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "origin", refspec, env=no_prompt)
    return git(root, "rev-parse", "--verify", f"{fetched}^{{commit}}")


def _strip_reviewer_configuration(tree: Path) -> None:
    for directory, subdirectories, files in os.walk(tree):
        for name in subdirectories + files:
            if name.lower() in _REVIEWER_CONFIGURATION:
                path = Path(directory, name)
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        subdirectories[:] = [name for name in subdirectories if name.lower() not in _REVIEWER_CONFIGURATION]


def _freeze_working_tree(root: Path) -> str:
    """The working tree frozen as an unreferenced commit on top of HEAD.

    Untracked files are included and ignored ones are not. It is built in a
    temporary copy of the index, so the user's index is never modified.
    """
    index = Path(git(root, "rev-parse", "--git-path", "index"))
    index = index if index.is_absolute() else root / index
    with tempfile.TemporaryDirectory(prefix="claude-delegate-") as tmp:
        scratch_index = Path(tmp) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch_index), **_TECHNICAL_IDENTITY}
        if index.exists():
            # copy2 keeps the index timestamp: git compares entries with it to
            # re-read files changed in the same second as the last staging.
            shutil.copy2(index, scratch_index)
        else:
            git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "--all", env=env)
        tree = git(root, "write-tree", env=env)
        return git(root, "commit-tree", tree, "-p", "HEAD", "-m", "claude-delegate : révision relue", env=env)


def _entry(root: Path, revision: str, path: str) -> Optional[Tuple[str, str]]:
    """("file", text) or ("link", target) for a path of `revision`; None when it
    is absent or is not a file, such as a directory."""
    listed = _run(root, ("ls-tree", "-z", revision, "--", path))
    if listed.returncode != 0:
        raise _unreadable(path, listed)
    if not listed.stdout:
        return None
    mode, kind, sha = listed.stdout.split("\0", 1)[0].partition("\t")[0].split()
    if kind != "blob":
        return None
    blob = _run(root, ("cat-file", "blob", sha))
    if blob.returncode != 0:
        raise _unreadable(path, blob)
    return ("link" if mode == "120000" else "file", blob.stdout)


def _unreadable(path: str, done: "subprocess.CompletedProcess[str]") -> DelegateError:
    """A conventions file git cannot read: reviewing without it would hide that."""
    return DelegateError(
        f"conventions illisibles : {path} au merge-base ({done.stderr.strip()})", EXIT_PREPARATION
    )


def _git_or_none(cwd: Path, *args: str) -> Optional[str]:
    """An optional git lookup: its output, or None when it fails or prints nothing."""
    done = _run(cwd, args)
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _run(
    cwd: Path, args: Tuple[str, ...], env: Optional[Dict[str, str]] = None
) -> "subprocess.CompletedProcess[str]":
    # Reviewed files may hold any bytes: invalid UTF-8 is replaced, not fatal.
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, encoding="utf-8", errors="replace"
    )
