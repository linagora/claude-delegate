"""The project conventions the reviewer may trust: the root CLAUDE.md of a
trusted revision, with its imports read from the same revision."""

from __future__ import annotations

import posixpath
import re
from typing import Callable, Optional, Tuple

from . import policy

#: Reads a file of the trusted revision: its text, or None when it is absent.
Reader = Callable[[str], Optional[str]]

#: A CLAUDE.md line made only of `@path` imports that file, as in Claude Code.
_IMPORT = re.compile(r"^@(\S+)\s*$")
_MAX_IMPORT_DEPTH = 5


def trusted(read: Reader) -> Optional[str]:
    """The root CLAUDE.md with its imports resolved, or None when there is none."""
    text = _with_imports(read, "CLAUDE.md", chain=())
    return text if text and text.strip() else None


def _with_imports(read: Reader, path: str, chain: Tuple[str, ...]) -> Optional[str]:
    """`chain` lists the files that led to this one, outermost first."""
    if path in chain or len(chain) > _MAX_IMPORT_DEPTH:
        return None
    content = read(path)
    if content is None:
        return None
    lines = []
    for line in content.splitlines():
        match = _IMPORT.match(line)
        target = _imported_path(path, match.group(1)) if match else None
        imported = _with_imports(read, target, chain + (path,)) if target else None
        lines.append(line if imported is None else imported)
    return "\n".join(lines)


def _imported_path(importer: str, reference: str) -> Optional[str]:
    """A path inside the repository, relative to the importing file. Home and
    absolute paths are never followed: they are not part of the revision. Nor
    are files the reviewer may not read, whatever the channel."""
    if reference.startswith(("~", "/")):
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(importer), reference))
    return None if path.startswith("..") or policy.is_denied(path) else path
