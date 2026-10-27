"""Read a country flag prefix without changing the stored profile name."""

from __future__ import annotations

import re

_FLAG_PREFIX = re.compile(r"^(\s*)([\U0001f1e6-\U0001f1ff]{2})\ufe0f?")
_FLAG = re.compile(r"[\U0001f1e6-\U0001f1ff]{2}\ufe0f?")


def flag_parts(text: str) -> list[tuple[str | None, str]]:
    """Split inline flags and text, preserving all characters and their order."""
    parts = []
    start = 0
    for match in _FLAG.finditer(text):
        if match.start() > start:
            parts.append((None, text[start : match.start()]))
        code = "".join(chr(ord(char) - 0x1F1E6 + ord("a")) for char in match[0][:2])
        parts.append((code, match[0]))
        start = match.end()
    if start < len(text):
        parts.append((None, text[start:]))
    return parts


def split_flag_prefix(text: str) -> tuple[str | None, str]:
    match = _FLAG_PREFIX.match(text)
    if match is None:
        return None, text
    code = "".join(chr(ord(char) - 0x1F1E6 + ord("a")) for char in match[2])
    return code, text[match.end() :].lstrip()
