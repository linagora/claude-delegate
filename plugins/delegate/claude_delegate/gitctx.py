"""What the reviewer reads: the diff to review, prepared from git."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .errors import DelegateError


@dataclass(frozen=True)
class HostileContext:
    root: Path
    origin_url: Optional[str]
    base: str
    merge_base: str
    diff: str


def hostile_context(cwd: Path, base: Optional[str]) -> HostileContext:
    root = Path(git(cwd, "rev-parse", "--show-toplevel"))
    base = base or default_base(root)
    merge_base = git(root, "merge-base", base, "HEAD")
    diff = git(root, "diff", "--no-color", "--no-ext-diff", merge_base, strip=False)
    return HostileContext(
        root=root, origin_url=origin_url(root), base=base, merge_base=merge_base, diff=diff
    )


def default_base(root: Path) -> str:
    """The default branch of origin (origin/HEAD), else main."""
    return _git_or_none(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "main"


def origin_url(root: Path) -> Optional[str]:
    return _git_or_none(root, "remote", "get-url", "origin")


def git(cwd: Path, *args: str, strip: bool = True) -> str:
    """A git command the review cannot do without: its failure is reported."""
    done = _run(cwd, args)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}")
    return done.stdout.strip() if strip else done.stdout


def _git_or_none(cwd: Path, *args: str) -> Optional[str]:
    """An optional git lookup: its output, or None when it fails or prints nothing."""
    done = _run(cwd, args)
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def _run(cwd: Path, args: Tuple[str, ...]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
