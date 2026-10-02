"""Command-line interface: one subcommand per delegated task."""

from __future__ import annotations

import argparse
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import __version__, archive, delegate, gitctx, interpret, prompts, recheck, report, schemas, selftest
from .errors import EXIT_SELFTEST, DelegateError


def main(argv: Optional[List[str]] = None) -> int:
    _exit_cleanly_on_termination()
    parser = argparse.ArgumentParser(
        prog="claude-delegate",
        description="Délègue des revues de code à une session Claude Code isolée sur Anthropic.",
    )
    parser.add_argument("--version", action="version", version=f"claude-delegate {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    hostile = commands.add_parser("hostile-review", help="Revue hostile des changements en cours.")
    hostile.add_argument("base", nargs="?", help="Branche de base (défaut : branche par défaut d'origin).")
    _add_model_option(hostile)
    pull_request = commands.add_parser("pr-review", help="Revue d'une pull request GitHub, sur son propre code.")
    pull_request.add_argument("number", type=_pull_request_number, help="Numéro de la pull request.")
    _add_model_option(pull_request)
    recheck_command = commands.add_parser(
        "recheck", help="Re-revue après corrections : statue sur chaque constat de la revue d'origine."
    )
    recheck_command.add_argument(
        "report", nargs="?", help="Identifiant ou chemin du rapport (défaut : le dernier rapport du dépôt)."
    )
    commands.add_parser(
        "selftest",
        help="Vérifie sur le vrai Claude Code que le relecteur reste isolé (Haiku, quelques centimes).",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "selftest":
            return _selftest()
        if args.command == "pr-review":
            return _pr_review(args.number, args.model)
        if args.command == "recheck":
            return _recheck(args.report)
        return _hostile_review(args.base, args.model)
    except DelegateError as error:
        print(f"claude-delegate : {error}", file=sys.stderr)
        return error.exit_code


def _add_model_option(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--model",
        choices=delegate.MODELS,
        default=delegate.DEFAULT_MODEL,
        help=f"Modèle du relecteur (défaut : {delegate.DEFAULT_MODEL}).",
    )


def _pull_request_number(text: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise argparse.ArgumentTypeError(f"numéro de pull request invalide : {text!r}")
    return int(text)


def _hostile_review(base: Optional[str], model: str) -> int:
    ctx = gitctx.hostile_context(Path.cwd(), base)
    done, execution = delegate.launch(
        ctx.root,
        ctx.diff,
        schemas.HOSTILE_REVIEW,
        prompts.hostile_review(ctx.conventions),
        "Revue hostile du diff fourni sur l'entrée standard.",
        model=model,
    )
    review = interpret.read_review(done)
    return _publish(archive.repo_key(ctx.root, ctx.origin_url), report.hostile_subject(ctx), execution, review)


def _pr_review(number: int, model: str) -> int:
    ctx = gitctx.pull_request_context(Path.cwd(), number)
    with gitctx.pull_request_worktree(ctx.root, ctx.pull_request.head) as tree:
        done, execution = delegate.launch(
            tree,
            ctx.reviewer_input(),
            schemas.PR_REVIEW,
            prompts.pr_review(ctx.conventions),
            "Revue de la pull request fournie sur l'entrée standard.",
            model=model,
        )
    review = interpret.read_pr_review(done)
    return _publish(archive.repo_key(ctx.root, ctx.origin_url), report.pr_subject(ctx), execution, review)


def _recheck(designation: Optional[str]) -> int:
    root = gitctx.repository(Path.cwd())
    repo = archive.repo_key(root, gitctx.origin_url(root))
    original = recheck.original(archive.state_dir() / repo, repo, designation)
    ctx = gitctx.recheck_context(root, original.base, original.reviewed_revision)
    done, execution = delegate.launch(
        root,
        recheck.reviewer_input(original, ctx),
        schemas.recheck([finding.id for finding in original.ruled]),
        prompts.recheck(ctx.conventions),
        "Re-revue des corrections décrites sur l'entrée standard.",
        model=original.requested_model,
    )
    review = interpret.read_recheck(done, original.ruled, original.next_number)
    return _publish(repo, report.recheck_subject(original.id, ctx), execution, review)


def _publish(repo: str, subject: report.Subject, execution: delegate.Execution, review: interpret.Review) -> int:
    """Archive the report, then print its path and its Markdown for the session."""
    created_at = datetime.now(timezone.utc)
    review_report = report.Report(
        id=archive.new_id(subject.slug, created_at),
        created_at=created_at,
        repo=repo,
        subject=subject,
        execution=execution,
        review=review,
    )
    markdown = review_report.markdown()
    try:
        path = archive.save(archive.state_dir() / repo, review_report.id, markdown, review_report.companion())
    except OSError as error:
        raise DelegateError(f"impossible d'archiver le rapport : {error}") from None
    sys.stdout.write(f"Rapport : {path}\n\n{markdown}")
    return 0


def _selftest() -> int:
    outcome = selftest.run()
    sys.stdout.write(selftest.render(outcome))
    return 0 if outcome.verdict == selftest.PASSED else EXIT_SELFTEST


def _exit_cleanly_on_termination() -> None:
    """A timeout or a cancelled command sends SIGTERM (SIGHUP when the terminal
    closes), which by default kills the CLI on the spot: the reviewer would keep
    running and temporary files (trap, worktrees) would stay. Raising SystemExit
    instead unwinds normally: subprocess.run kills the reviewer, and temporary
    directories are removed."""

    def terminate(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), terminate)
