"""What the reviewer reads, prepared from git: the diff to review, the trusted
conventions and, for a pull request, a throwaway worktree of its code."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from . import conventions, forge, policy
from .errors import EXIT_PREPARATION, DelegateError

#: Denied files stay out of the diff too, since the reviewer may not read them.
_DENIED = [f":(exclude,glob){path}" for path in policy.DENIED_PATHS]
#: The same files, to name those a change touches.
_ONLY_DENIED = [f":(glob){path}" for path in policy.DENIED_PATHS]

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


@dataclass(frozen=True)
class PullRequestContext:
    root: Path
    origin_url: Optional[str]
    pull_request: forge.PullRequest
    #: The tip of the target branch on origin, fetched for the review.
    base_revision: str
    merge_base: str
    diff: str
    #: Changed files the reviewer may neither read nor see in the diff, as
    #: they may hold secrets: a human has to review them.
    unreviewed: List[str]
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
            f"Fichiers non relus : {', '.join(self.unreviewed) or 'aucun'}\n"
            "\n--- Début de la description de la pull request ---\n"
            f"{pr.body.strip() or '(aucune description)'}\n"
            "--- Fin de la description de la pull request ---\n"
            f"\n--- Début du diff, du merge-base avec {pr.base} jusqu'à la tête ---\n"
            f"{self.diff}"
            "--- Fin du diff ---\n"
        )


@dataclass(frozen=True)
class RecheckContext:
    base: str
    merge_base: str
    #: The revision the rechecked report read.
    original_revision: str
    #: The current state, frozen as a hostile review freezes it.
    reviewed_revision: str
    #: What changed since: from the original revision to the current one.
    gap: str
    #: The full current diff, from the merge-base.
    diff: str
    #: The root CLAUDE.md at the merge-base, never from the reviewed work.
    conventions: Optional[str]


def hostile_context(cwd: Path, base: Optional[str]) -> HostileContext:
    root = repository(cwd)
    base = base or default_base(root)
    merge_base = _merge_base(root, base)
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


def recheck_context(root: Path, base: str, original_revision: str) -> RecheckContext:
    if _commit(root, original_revision) is None:
        raise DelegateError(
            f"révision relue par le rapport d'origine introuvable ({original_revision[:12]}), sans doute purgée "
            "par git : lance une revue complète avec /delegate:hostile-review",
            EXIT_PREPARATION,
        )
    merge_base = _merge_base(root, base)
    reviewed_revision = _freeze_working_tree(root)
    # Possibly empty: fixes may undo the whole change, findings still get ruled.
    diff = _diff(root, merge_base, reviewed_revision)
    gap = _reviewable_diff(root, original_revision, reviewed_revision, "aucun changement depuis le rapport d'origine")
    size = len(gap) + len(diff)
    if size > MAX_DIFF_CHARS:
        raise _too_large(size)
    return RecheckContext(
        base=base,
        merge_base=merge_base,
        original_revision=original_revision,
        reviewed_revision=reviewed_revision,
        gap=gap,
        diff=diff,
        conventions=trusted_conventions(root, merge_base),
    )


def pull_request_context(cwd: Path, number: int) -> PullRequestContext:
    root = repository(cwd)
    origin = origin_url(root)
    pr = forge.pull_request(origin, number)
    base_revision = _fetch(root, f"refs/heads/{pr.base}")
    head = _fetch(root, pr.ref)
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
        unreviewed=_unreviewed_changes(root, merge_base, head),
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


def repository(cwd: Path) -> Path:
    """The root of the repository holding `cwd`."""
    toplevel = _git_or_none(cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        raise DelegateError(f"pas un dépôt git : {cwd}", EXIT_PREPARATION)
    return Path(toplevel)


def origin_url(root: Path) -> Optional[str]:
    """origin's URL as git reaches it, which resolves insteadOf aliases such as
    gh:owner/name. When a rule rewrites it to a local path (a mirror), the URL
    as configured still names the hosted repository."""
    reached = _git_or_none(root, "remote", "get-url", "origin")
    if reached is None or forge.parse_remote(reached) is not None:
        return reached
    configured = _git_or_none(root, "config", "--get-all", "remote.origin.url")
    return configured.splitlines()[0] if configured else reached


def git(cwd: Path, *args: str, strip: bool = True, env: Optional[Dict[str, str]] = None) -> str:
    """A git command the review cannot do without: its failure is reported."""
    done = _run(cwd, args, env)
    if done.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} a échoué : {done.stderr.strip()}", EXIT_PREPARATION)
    return done.stdout.strip() if strip else done.stdout


def _merge_base(root: Path, base: str) -> str:
    """Where the reviewed work starts from `base`: their merge-base with HEAD."""
    if _commit(root, "HEAD") is None:
        raise DelegateError("le dépôt n'a encore aucun commit", EXIT_PREPARATION)
    if _commit(root, base) is None:
        raise DelegateError(f"base introuvable : {base}", EXIT_PREPARATION)
    merge_base = _git_or_none(root, "merge-base", base, "HEAD")
    if merge_base is None:
        raise DelegateError(f"aucun ancêtre commun entre {base} et HEAD", EXIT_PREPARATION)
    return merge_base


def _commit(root: Path, revision: str) -> Optional[str]:
    """The commit `revision` names, or None when it names none."""
    return _git_or_none(root, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}")


def _diff(root: Path, start: str, end: str) -> str:
    """The diff from `start` to `end` that the reviewer receives, without denied files."""
    diff = git(root, "diff", "--no-color", "--no-ext-diff", start, end, "--", ".", *_DENIED, strip=False)
    if len(diff) > MAX_DIFF_CHARS:
        raise _too_large(len(diff))
    return diff


def _reviewable_diff(root: Path, start: str, end: str, empty_reason: str) -> str:
    """The diff from `start` to `end`, which must hold something to review:
    `empty_reason` says why it does not."""
    diff = _diff(root, start, end)
    if not diff.strip():
        unreviewed = _unreviewed_changes(root, start, end)
        if unreviewed:
            raise DelegateError(
                f"rien à relire : seuls changent des fichiers exclus de la revue ({', '.join(unreviewed)}), "
                "relis-les toi-même",
                EXIT_PREPARATION,
            )
        raise DelegateError(f"rien à relire : {empty_reason}", EXIT_PREPARATION)
    return diff


def _too_large(chars: int) -> DelegateError:
    size, limit = (f"{n:,}".replace(",", " ") for n in (chars, MAX_DIFF_CHARS))
    return DelegateError(
        f"diff trop volumineux pour une revue : {size} caractères (maximum {limit})", EXIT_PREPARATION
    )


def _unreviewed_changes(root: Path, start: str, end: str) -> List[str]:
    """Files changed from `start` to `end` that the reviewer may not read."""
    names = git(root, "diff", "--name-only", "-z", start, end, "--", *_ONLY_DENIED, strip=False)
    return [name for name in names.split("\0") if name]


def _fetch(root: Path, ref: str) -> str:
    """The commit of origin's `ref`, fetched without moving any ref of the
    repository: an empty --refmap stops git from updating the remote-tracking
    branch of a branch fetched by name."""
    no_prompt = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    git(root, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--refmap=", "origin", ref, env=no_prompt)
    return git(root, "rev-parse", "--verify", "FETCH_HEAD^{commit}")


def _strip_reviewer_configuration(tree: Path) -> None:
    for directory, subdirectories, files in os.walk(tree):
        for name in subdirectories + files:
            if policy.configures_the_reviewer(name):
                path = Path(directory, name)
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        subdirectories[:] = [name for name in subdirectories if not policy.configures_the_reviewer(name)]


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
        raise _unreadable(path, revision, listed)
    if not listed.stdout:
        return None
    mode, kind, sha = listed.stdout.split("\0", 1)[0].partition("\t")[0].split()
    if kind != "blob":
        return None
    blob = _run(root, ("cat-file", "blob", sha))
    if blob.returncode != 0:
        raise _unreadable(path, revision, blob)
    return ("link" if mode == "120000" else "file", blob.stdout)


def _unreadable(path: str, revision: str, done: "subprocess.CompletedProcess[str]") -> DelegateError:
    """A conventions file git cannot read: reviewing without it would hide that."""
    return DelegateError(
        f"conventions illisibles : {path} à la révision {revision[:12]} ({done.stderr.strip()})", EXIT_PREPARATION
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
