"""The project conventions the reviewer may trust: the root CLAUDE.md of a
trusted revision, with its imports read from the same revision."""

from __future__ import annotations

import posixpath
import re
from typing import Callable, Optional, Tuple

from . import policy

#: Reads an entry of the trusted revision: ("file", text), ("link", target),
#: or None when it is absent or is not a file.
Reader = Callable[[str], Optional[Tuple[str, str]]]

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
    entry = read(path)
    if entry is None:
        return None
    kind, content = entry
    if kind == "link":
        # A symlink, such as CLAUDE.md -> AGENTS.md, follows the import rules.
        target = _imported_path(path, content.strip())
        return _with_imports(read, target, chain + (path,)) if target else None
    lines = []
    for line in content.splitlines():
        match = _IMPORT.match(line)
        if not match:
            lines.append(line)
            continue
        target = _imported_path(path, match.group(1))
        imported = _with_imports(read, target, chain + (path,)) if target else None
        # An import left as `@path` could send the reviewer to read the file
        # from the reviewed tree, which is not trusted: say it was ignored.
        lines.append(f"(import ignoré : {match.group(1)})" if imported is None else imported)
    return "\n".join(lines)


def _imported_path(importer: str, reference: str) -> Optional[str]:
    """A path inside the repository, relative to the importing file. Home and
    absolute paths are never followed: they are not part of the revision. Nor
    are files the reviewer may not read, whatever the channel."""
    if reference.startswith(("~", "/")):
        return None
    path = posixpath.normpath(posixpath.join(posixpath.dirname(importer), reference))
    return None if path.startswith("..") or policy.is_denied(path) else path
