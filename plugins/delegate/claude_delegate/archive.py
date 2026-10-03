"""Where reports live, outside the repository with one directory per
repository, and how a recheck finds them again."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from . import forge
from .errors import EXIT_PREPARATION, DelegateError

#: Report identifiers, such as 20261002T120000Z-pr-7-a1b2c3.
_REPORT_ID = re.compile(r"\d{8}T\d{6}Z-[a-z0-9-]+-[0-9a-f]{6}")


def state_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME", "")
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "state"
    return base / "claude-delegate"


def repo_key(root: Path, origin_url: Optional[str]) -> str:
    """host/owner/name from the origin remote, else the directory name and a short hash."""
    remote = forge.parse_remote(origin_url) if origin_url else None
    if remote:
        return "/".join(_safe(segment) for segment in [remote.host, *remote.path.split("/")] if segment)
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{_safe(root.name)}-{digest}"


def new_id(slug: str, created_at: datetime) -> str:
    """Such as 20261002T120000Z-pr-7-a1b2c3: sortable, with what was reviewed."""
    return f"{created_at:%Y%m%dT%H%M%SZ}-{slug}-{secrets.token_hex(3)}"


def save(directory: Path, report_id: str, markdown: str, companion: Dict[str, Any]) -> Path:
    """Write the JSON companion, then the report: a report on disk is always complete."""
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / f"{report_id}.md"
    _atomic_write(report.with_suffix(".json"), json.dumps(companion, ensure_ascii=False, indent=2))
    _atomic_write(report, markdown)
    return report


def latest(directory: Path) -> Optional[Path]:
    """The companion of the most recent report in `directory`, if any. A report
    exists once its Markdown is written, after its companion."""
    reports = sorted(path for path in directory.glob("*.md") if path.with_suffix(".json").is_file())
    return reports[-1].with_suffix(".json") if reports else None


def is_report_id(text: str) -> bool:
    return _REPORT_ID.fullmatch(text) is not None


def find(directory: Path, designation: str) -> Path:
    """The companion of a report designated by its identifier, looked up in
    `directory`, or by the path of its Markdown or JSON."""
    missing = DelegateError(f"rapport introuvable : {designation}", EXIT_PREPARATION)
    if is_report_id(designation):
        companion = directory / f"{designation}.json"
    else:
        try:
            companion = Path(designation).with_suffix(".json")
        except ValueError:  # no file name, as in "." or "/"
            raise missing from None
    if not companion.is_file():
        raise missing
    return companion


def load(companion: Path) -> Dict[str, Any]:
    try:
        record = json.loads(companion.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DelegateError(f"rapport illisible : {companion} ({error})", EXIT_PREPARATION) from None
    if not isinstance(record, dict):
        raise DelegateError(f"rapport illisible : {companion}", EXIT_PREPARATION)
    return record


def _safe(segment: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", segment)
    return "_" if cleaned in (".", "..") else cleaned


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
