"""What the reviewer reads: the diff to review, prepared from git."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .errors import DelegateError

#: Identity of the technical commit that freezes the reviewed revision, so that
#: building it never depends on the user's git configuration.
_SNAPSHOT_IDENTITY = {
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
    snapshot: str
    diff: str


def hostile_context(cwd: Path, base: Optional[str]) -> HostileContext:
    root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    base = base or default_base(root)
    merge_base = git(root, "merge-base", base, "HEAD")
    snapshot = _snapshot(root)
    diff = git(root, "diff", "--no-color", "--no-ext-diff", merge_base, snapshot, strip=False)
    return HostileContext(
        root=root,
        origin_url=origin_url(root),
        base=base,
        merge_base=merge_base,
        snapshot=snapshot,
        diff=diff,
    )


def default_base(root: Path) -> str:
    """The default branch of origin (origin/HEAD), else main."""
    return _git_or_none(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "main"


def origin_url(root: Path) -> Optional[str]:
    return _git_or_none(root, "remote", "get-url", "origin")


def git(cwd: Path, *args: str, strip: bool = True, env: Optional[Dict[str, str]] = None) -> str:
    """A git command the review cannot do without: its failure is reported."""
    done = _run(cwd, args, env)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}")
    return done.stdout.strip() if strip else done.stdout


def _snapshot(root: Path) -> str:
    """The working tree frozen as an unreferenced commit on top of HEAD.

    Untracked files are included and ignored ones are not. It is built in a
    temporary copy of the index, so the user's index is never modified.
    """
    index = Path(git(root, "rev-parse", "--git-path", "index"))
    index = index if index.is_absolute() else root / index
    with tempfile.TemporaryDirectory(prefix="claude-delegate-") as tmp:
        scratch_index = Path(tmp) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch_index), **_SNAPSHOT_IDENTITY}
        if index.exists():
            shutil.copyfile(index, scratch_index)
        else:
            git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "--all", env=env)
        tree = git(root, "write-tree", env=env)
        return git(root, "commit-tree", tree, "-p", "HEAD", "-m", "claude-delegate : révision relue", env=env)


def _git_or_none(cwd: Path, *args: str) -> Optional[str]:
    """An optional git lookup: its output, or None when it fails or prints nothing."""
    done = _run(cwd, args)
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _run(
    cwd: Path, args: Tuple[str, ...], env: Optional[Dict[str, str]] = None
) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
