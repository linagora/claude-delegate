"""Command-line interface: one subcommand per delegated task."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, archive, delegate, gitctx, report
from .errors import DelegateError


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-delegate",
        description="Délègue des revues de code à une session Claude Code isolée sur Anthropic.",
    )
    parser.add_argument("--version", action="version", version=f"claude-delegate {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    hostile = commands.add_parser("hostile-review", help="Revue hostile des changements en cours.")
    hostile.add_argument("base", nargs="?", help="Branche de base (défaut : branche par défaut d'origin).")
    args = parser.parse_args(argv)

    try:
        return _hostile_review(args.base)
    except DelegateError as error:
        print(f"claude-delegate : {error}", file=sys.stderr)
        return error.exit_code


def _hostile_review(base: Optional[str]) -> int:
    ctx = gitctx.hostile_context(Path.cwd(), base)
    review = delegate.review(ctx)
    created_at = archive.now()
    report_id = archive.new_id("hostile", created_at)
    repo = archive.repo_key(ctx.root, ctx.origin_url)
    header = [
        ("Identifiant", report_id),
        ("Date (UTC)", f"{created_at:%Y-%m-%d %H:%M:%S}"),
        ("Dépôt", repo),
        ("Base", f"{ctx.base} (merge-base {ctx.merge_base[:12]})"),
        ("Modèle", review.model),
    ]
    markdown = report.render("Revue hostile", header, review)
    companion = {
        "id": report_id,
        "type": "hostile",
        "created_at": created_at.isoformat(),
        "repo": repo,
        "base": ctx.base,
        "merge_base": ctx.merge_base,
        "model": review.model,
        "summary": review.summary,
        "findings": review.findings,
    }
    path = archive.save(archive.state_dir() / repo, report_id, markdown, companion)
    sys.stdout.write(f"Rapport : {path}\n\n{markdown}")
    return 0
