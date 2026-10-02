"""What the reviewer reads: the diff to review, prepared from git."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    done = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "main"


def origin_url(root: Path) -> Optional[str]:
    done = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True
    )
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def git(cwd: Path, *args: str, strip: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}")
    return done.stdout.strip() if strip else done.stdout
