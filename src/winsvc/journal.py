"""Журнал отката службы: схема записей поверх `src.core.net_journal`.

Запись делается до изменения, кроме NRPT: имя правила известно только после
создания.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

from src.core import net_journal

_GUID = re.compile(
    r"\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}"
)


def _valid(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    op = entry.get("op")
    if op == "route.delete":
        try:
            ipaddress.IPv4Network(str(entry.get("prefix")))
        except ValueError:
            return False
        return isinstance(entry.get("index"), int) and entry["index"] > 0
    if op == "nrpt.remove":
        return bool(_GUID.fullmatch(str(entry.get("name", ""))))
    return False


class Journal(net_journal.Journal):
    def __init__(self, path: Path) -> None:
        super().__init__(path, _valid)
