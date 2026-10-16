"""Turns a title into a URL slug."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Return title in lowercase ASCII, each run of other characters turned
    into a single hyphen, with no hyphen at either end."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub("-", ascii_title.lower()).strip("-")
