"""Where reports live: outside the repository, one directory per repository."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit


def state_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME", "")
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "state"
    return base / "claude-delegate"


def repo_key(root: Path, origin_url: Optional[str]) -> str:
    """host/owner/name from the origin remote, else the directory name and a short hash."""
    from_origin = _remote_key(origin_url) if origin_url else None
    if from_origin:
        return from_origin
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{_safe(root.name)}-{digest}"


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(kind: str, created_at: datetime) -> str:
    return f"{created_at:%Y%m%dT%H%M%SZ}-{kind}-{secrets.token_hex(3)}"


def save(directory: Path, report_id: str, markdown: str, companion: Dict[str, Any]) -> Path:
    """Write the JSON companion, then the report: a report on disk is always complete."""
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / f"{report_id}.md"
    _atomic_write(report.with_suffix(".json"), json.dumps(companion, ensure_ascii=False, indent=2))
    _atomic_write(report, markdown)
    return report


def _remote_key(url: str) -> Optional[str]:
    scp_like = re.match(r"^(?:[^@/]+@)?([^:/]+):(?!//)(.+)$", url)
    if scp_like and "://" not in url:
        host, path = scp_like.group(1), scp_like.group(2)
    else:
        parts = urlsplit(url)  # .hostname drops any user:token@ prefix
        host, path = parts.hostname or "", parts.path
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not host or not path:
        return None
    return "/".join(_safe(segment) for segment in [host, *path.split("/")] if segment)


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
