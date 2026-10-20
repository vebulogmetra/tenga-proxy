"""Sanitize text at logging sinks, including formatted exceptions and old logs."""

from __future__ import annotations

import logging
import re

_LINK = re.compile(
    r"\b(?:https?|ss|ssr|vmess|vless|trojan|hy2|hysteria2|veblock|wingeon)://[^\s\"'<>]+", re.I
)
_QUOTED = r"""(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*')"""
_AUTH = re.compile(
    r"""["']?\b(?:authorization|proxy-authorization)["']?\s*[:=]\s*"""
    + r"(?:"
    + _QUOTED
    + r"|[^\r\n]+)",
    re.I,
)
_SECRET = re.compile(
    r"""(?i)(["']?\b(?:password|passwd|pwd|pass|token|secret|api[_-]?key|access[_-]?token|"""
    r"""auth(?:[_-]?token)?|id|username|client[_-]?secret|uuid|user(?:id|_id)?|short[_-]?id|"""
    r"""x-hwid|hwid|sid)["']?\s*[=:]\s*)(?:""" + _QUOTED + r"""|[^\s,;&}\]]+)"""
)
_UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)


def redact(text: str) -> str:
    text = re.sub(r"(?i)\bBearer\s+[^\s\"'<>]+", "Bearer [скрыто]", text)
    text = _AUTH.sub("Authorization: [скрыто]", text)
    text = _LINK.sub(lambda match: match.group().split(":", 1)[0] + "://[скрыто]", text)
    text = _SECRET.sub(lambda match: match[1] + "[скрыто]", text)
    return _UUID.sub("[uuid скрыт]", text)


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args, delegate=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        formatted = self._delegate.format(record) if self._delegate else super().format(record)
        return redact(formatted)
