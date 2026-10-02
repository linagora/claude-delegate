"""What the reviewer reads: the diff to review, prepared from git."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import conventions, policy
from .errors import EXIT_PREPARATION, DelegateError

#: Denied files stay out of the diff too, since the reviewer may not read them.
_DENIED = [f":(exclude,glob){path}" for path in policy.DENIED_PATHS]

#: Beyond this (about 250k tokens), a review costs too much to be useful.
MAX_DIFF_CHARS = 1_000_000

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


def hostile_context(cwd: Path, base: Optional[str]) -> HostileContext:
    toplevel = _git_or_none(cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        raise DelegateError(f"pas un dépôt git : {cwd}", EXIT_PREPARATION)
    root = Path(toplevel)
    if _git_or_none(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}") is None:
        raise DelegateError("le dépôt n'a encore aucun commit", EXIT_PREPARATION)
    base = base or default_base(root)
    if _git_or_none(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}") is None:
        raise DelegateError(f"base introuvable : {base}", EXIT_PREPARATION)
    merge_base = _git_or_none(root, "merge-base", base, "HEAD")
    if merge_base is None:
        raise DelegateError(f"aucun ancêtre commun entre {base} et HEAD", EXIT_PREPARATION)
    reviewed_revision = _freeze_working_tree(root)
    diff = git(
        root, "diff", "--no-color", "--no-ext-diff", merge_base, reviewed_revision, "--", ".", *_DENIED, strip=False
    )
    if not diff.strip():
        raise DelegateError(f"rien à relire : aucun changement depuis {base}", EXIT_PREPARATION)
    if len(diff) > MAX_DIFF_CHARS:
        size, limit = (f"{n:,}".replace(",", " ") for n in (len(diff), MAX_DIFF_CHARS))
        raise DelegateError(
            f"diff trop volumineux pour une revue : {size} caractères (maximum {limit})", EXIT_PREPARATION
        )
    return HostileContext(
        root=root,
        origin_url=origin_url(root),
        base=base,
        merge_base=merge_base,
        reviewed_revision=reviewed_revision,
        diff=diff,
        conventions=trusted_conventions(root, merge_base),
    )


def trusted_conventions(root: Path, revision: str) -> Optional[str]:
    """The conventions as they are at `revision`, so the reviewed work cannot change them."""
    return conventions.trusted(lambda path: _show(root, revision, path))


def default_base(root: Path) -> str:
    """The default branch of origin (origin/HEAD), else main."""
    return _git_or_none(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "main"


def origin_url(root: Path) -> Optional[str]:
    return _git_or_none(root, "remote", "get-url", "origin")


def git(cwd: Path, *args: str, strip: bool = True, env: Optional[Dict[str, str]] = None) -> str:
    """A git command the review cannot do without: its failure is reported."""
    done = _run(cwd, args, env)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}", EXIT_PREPARATION)
    return done.stdout.strip() if strip else done.stdout


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


def _show(root: Path, revision: str, path: str) -> Optional[str]:
    done = _run(root, ("show", f"{revision}:{path}"))
    return done.stdout if done.returncode == 0 else None


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
