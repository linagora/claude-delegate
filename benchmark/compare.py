#!/usr/bin/env python3
"""Compare the reviewer models on reference cases.

Each case is a directory holding what a branch looked like before the change
(`before/`), what it looks like after (`after/`), and a `case.json` describing
the defects the change introduces. For every model, the script builds a real
repository out of a case, runs the plugin's own `hostile-review` on it, and
scores the report:

- **recall** — how many of the planted defects were found;
- **invented** — findings that match no planted defect, which cost triage time;
- **cost and duration** — as the report already records them.

A defect is judged found when a finding names its file and mentions one of its
keywords. The keywords, not the wording, decide: two models phrase the same
defect differently, so matching on an exact sentence would measure style.

This is a measurement, not a test: it is not run by `unittest discover`, and it
is not offline unless `--dry-run` is used. A real run calls Anthropic and costs
money, once per case and per model.

    python3 benchmark/compare.py --dry-run                  # free: plumbing only
    python3 benchmark/compare.py --models opus sonnet fable  # a real measurement
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "plugins" / "delegate" / "bin" / "claude-delegate"
CASES = Path(__file__).resolve().parent / "cases"
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "claude-delegate",
    "GIT_AUTHOR_EMAIL": "claude-delegate@localhost",
    "GIT_COMMITTER_NAME": "claude-delegate",
    "GIT_COMMITTER_EMAIL": "claude-delegate@localhost",
}


@dataclass(frozen=True)
class Planted:
    id: str
    severity: str
    file: str
    line: Optional[int]
    problem: str
    keywords: List[str]


@dataclass(frozen=True)
class Case:
    name: str
    directory: Path
    title: str
    why: str
    planted: List[Planted]

    @property
    def before(self) -> Path:
        return self.directory / "before"

    @property
    def after(self) -> Path:
        return self.directory / "after"


@dataclass
class Outcome:
    """What one model produced on one case."""

    model: str
    case: str
    found: List[str] = field(default_factory=list)
    missed: List[str] = field(default_factory=list)
    invented: List[Dict[str, Any]] = field(default_factory=list)
    cost_usd: Optional[float] = None
    duration_s: Optional[float] = None
    failure: Optional[str] = None

    @property
    def recalled(self) -> int:
        return len(self.found)

    @property
    def planted(self) -> int:
        return self.recalled + len(self.missed)


def load_cases() -> List[Case]:
    cases = []
    for directory in sorted(path for path in CASES.iterdir() if path.is_dir()):
        specification = json.loads((directory / "case.json").read_text(encoding="utf-8"))
        cases.append(
            Case(
                name=directory.name,
                directory=directory,
                title=specification["title"],
                why=specification["why"],
                planted=[Planted(**defect) for defect in specification["planted"]],
            )
        )
    return cases


def _git(cwd: Path, *args: str, env: Optional[Dict[str, str]] = None) -> None:
    done = subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **GIT_IDENTITY, **(env or {})},
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} a échoué dans {cwd} : {done.stderr.strip()}")


def _copy(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def build_repository(case: Case, root: Path, model: str) -> Path:
    """A repository where `main` holds `before/` and the current branch holds
    `after/` as one commit, which is what a hostile review reads."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet", "-b", "main", str(root))
    _copy(case.before, root)
    _git(root, "add", "--all")
    _git(root, "commit", "--quiet", "-m", "before")
    _git(root, "switch", "--quiet", "-c", "feature")
    _copy(case.after, root)
    _git(root, "add", "--all")
    _git(root, "commit", "--quiet", "-m", f"{case.name} : change reviewed by {model}")
    return root


def review(case: Case, model: str, state: Path, dry_run: bool) -> Outcome:
    """Run the plugin's own hostile review on the case, as a user would."""
    outcome = Outcome(model=model, case=case.name)
    with tempfile.TemporaryDirectory(prefix=f"benchmark-{case.name}-{model}-") as tmp:
        repository = build_repository(case, Path(tmp) / "repo", model)
        environment = {
            **os.environ,
            "XDG_STATE_HOME": str(state),
            "HOME": os.environ.get("HOME", str(state)),
        }
        outcome.failure = run_review(repository, case, model, environment, outcome, dry_run)
    return outcome


def run_review(
    repository: Path,
    case: Case,
    model: str,
    environment: Dict[str, str],
    outcome: Outcome,
    dry_run: bool,
) -> Optional[str]:
    """The CLI run, read back from the report it archives. Returns a failure note."""
    environment = dict(environment)
    if dry_run:
        sys.path.insert(0, str(ROOT))
        from benchmark.fake_reviewer import install  # late: a real run needs nothing from it

        environment["CLAUDE_DELEGATE_BIN"] = install()
    done = subprocess.run(
        [sys.executable, str(CLI), "hostile-review", "main", "--model", model],
        cwd=repository, env=environment, capture_output=True, text=True,
    )
    if done.returncode != 0:
        return f"the review failed ({done.returncode}): {done.stderr.strip()[:200]}"
    report = _report_path(done.stdout)
    if report is None:
        return "the review printed no report path"
    record = json.loads(report.with_suffix(".json").read_text(encoding="utf-8"))
    outcome.cost_usd = record.get("cost_usd")
    outcome.duration_s = record.get("duration_s")
    score(outcome, record["findings"], case)
    return None


def _report_path(stdout: str) -> Optional[Path]:
    first = stdout.partition("\n")[0]
    return Path(first[len("Rapport : "):]) if first.startswith("Rapport : ") else None


def score(outcome: Outcome, findings: Sequence[Any], case: Case) -> None:
    """Split findings into the planted defects they name and the rest."""
    matched: set = set()
    for finding in findings:
        defect = matching_defect(finding, case)
        if defect is None:
            outcome.invented.append(finding)
        else:
            matched.add(defect.id)
    outcome.found = [defect.id for defect in case.planted if defect.id in matched]
    outcome.missed = [defect.id for defect in case.planted if defect.id not in matched]


def matching_defect(finding: Dict[str, Any], case: Case) -> Optional[Planted]:
    """The planted defect a finding names, if any: same file, one keyword in the
    text it wrote about it. Wording differs between models; keywords do not."""
    said = " ".join(
        str(finding.get(field) or "") for field in ("problem", "failure_scenario", "fix")
    ).lower()
    for defect in case.planted:
        if defect.file != finding.get("file"):
            continue
        if any(keyword.lower() in said for keyword in defect.keywords):
            return defect
    return None


def render(outcomes: List[Outcome]) -> str:
    """A table of what each model found, per case."""
    lines = [
        "| Modèle | Cas | Rappel | Inventés | Coût | Durée |",
        "|---|---|---|---|---|---|",
    ]
    for outcome in outcomes:
        if outcome.failure:
            lines.append(f"| {outcome.model} | {outcome.case} | — | — | — | {outcome.failure} |")
            continue
        recall = f"{outcome.recalled}/{outcome.planted}"
        cost = "—" if outcome.cost_usd is None else f"{outcome.cost_usd:.2f} $"
        duration = "—" if outcome.duration_s is None else f"{outcome.duration_s:.0f} s"
        lines.append(
            f"| {outcome.model} | {outcome.case} | {recall} | {len(outcome.invented)} "
            f"| {cost} | {duration} |"
        )
    return "\n".join(lines) + "\n"


def summary(outcomes: List[Outcome]) -> str:
    """Recall and invented findings, totalled per model: the two numbers the
    default model should be chosen on."""
    models = sorted({outcome.model for outcome in outcomes})
    lines = ["", "| Modèle | Défauts trouvés | Défauts manqués | Constats inventés |", "|---|---|---|---|"]
    for model in models:
        mine = [outcome for outcome in outcomes if outcome.model == model and not outcome.failure]
        lines.append(
            f"| {model} | {sum(o.recalled for o in mine)} | {sum(len(o.missed) for o in mine)} "
            f"| {sum(len(o.invented) for o in mine)} |"
        )
    return "\n".join(lines) + "\n"


def detail(outcomes: List[Outcome], cases: List[Case]) -> str:
    """What was invented, so that a human can rule on it. A keyword match is a
    hint, not a verdict: an invented finding may be a real defect the case did
    not plant, and only reading it says which."""
    lines = []
    for outcome in outcomes:
        if outcome.failure or not outcome.invented:
            continue
        case = next(case for case in cases if case.name == outcome.case)
        lines += ["", f"### {outcome.model} sur {outcome.case} — {len(outcome.invented)} constat(s) inventé(s)"]
        for finding in outcome.invented:
            location = f"{finding.get('file')}:{finding.get('line')}"
            lines.append(f"- {location} ({finding.get('severity')}) : {finding.get('problem')}")
    return "\n".join(lines) + "\n" if lines else ""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=["opus", "sonnet", "fable"])
    parser.add_argument("--cases", nargs="+", help="Cas à mesurer (défaut : tous).")
    parser.add_argument("--dry-run", action="store_true", help="Ne pas appeler Anthropic : vérifie la plomberie.")
    parser.add_argument("--out", type=Path, help="Écrire le compte rendu dans ce fichier, en plus de la sortie.")
    arguments = parser.parse_args(argv)

    cases = load_cases()
    if arguments.cases:
        wanted = set(arguments.cases)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        if missing:
            raise SystemExit(f"cas inconnus : {', '.join(sorted(missing))}")

    with tempfile.TemporaryDirectory(prefix="benchmark-state-") as state:
        outcomes = [review(case, model, Path(state), arguments.dry_run) for case in cases for model in arguments.models]

    report = render(outcomes) + summary(outcomes) + detail(outcomes, cases)
    if arguments.dry_run:
        report = "Mesure à blanc : la plomberie seule, aucun appel au modèle.\n\n" + report
    sys.stdout.write(report)
    if arguments.out:
        arguments.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
