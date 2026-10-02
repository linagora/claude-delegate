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
#: Imports are not evaluated inside fenced code blocks.
_FENCE = re.compile(r"^\s*(```|~~~)")
_MAX_IMPORT_DEPTH = 5
#: Bounds on what the conventions may add to every review's prompt.
MAX_IMPORTED_FILES = 20
MAX_CHARS = 100_000


def trusted(read: Reader) -> Optional[str]:
    """The root CLAUDE.md with its imports resolved, or None when there is none."""
    text = _Resolver(read).resolve("CLAUDE.md", chain=())
    if not text or not text.strip():
        return None
    if len(text) > MAX_CHARS:
        limit = f"{MAX_CHARS:,}".replace(",", " ")
        return f"{text[:MAX_CHARS]}\n(conventions tronquées à {limit} caractères)"
    return text


class _Resolver:
    def __init__(self, read: Reader) -> None:
        self._read = read
        self._imports_left = MAX_IMPORTED_FILES

    def resolve(self, path: str, chain: Tuple[str, ...]) -> Optional[str]:
        """The file's text with its imports resolved; `chain` lists the files
        that led to it, outermost first."""
        if path in chain or len(chain) > _MAX_IMPORT_DEPTH:
            return None
        if chain and self._imports_left <= 0:
            return None
        entry = self._read(path)
        if entry is None:
            return None
        kind, content = entry
        if kind == "link":
            # A symlink, such as CLAUDE.md -> AGENTS.md, follows the import rules.
            target = _imported_path(path, content.strip())
            return self.resolve(target, chain + (path,)) if target else None
        if "\x00" in content:
            return None  # binary: nothing a reviewer could use as conventions
        if chain:
            self._imports_left -= 1
        return self._expand(path, content, chain + (path,))

    def _expand(self, path: str, content: str, chain: Tuple[str, ...]) -> str:
        lines = []
        in_code_block = False
        for line in content.splitlines():
            if _FENCE.match(line):
                in_code_block = not in_code_block
            match = None if in_code_block else _IMPORT.match(line)
            if not match:
                lines.append(line)
                continue
            target = _imported_path(path, match.group(1))
            imported = self.resolve(target, chain) if target else None
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
