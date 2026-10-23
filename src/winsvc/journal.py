"""Журнал отката: что служба изменила в сети и как это вернуть.

Запись делается до изменения (кроме NRPT, имя правила которого известно только
после создания), файл переписывается атомарно. Откат идёт в обратном порядке,
сбой одного шага не останавливает остальные. При загрузке записи проверяются
по схеме: файл лежит на диске, и доверять ему как коду нельзя.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("tenga.winsvc.journal")

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


class Journal:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Journal is unreadable, starting empty: %s", e)
            return []
        entries = data if isinstance(data, list) else []
        valid = [entry for entry in entries if _valid(entry)]
        if len(valid) != len(entries):
            logger.warning("Dropped %d malformed journal entries", len(entries) - len(valid))
        return valid

    def _save(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries), encoding="utf-8")
        os.replace(tmp, self._path)

    def entries(self) -> list[dict]:
        with self._lock:
            return self._load()

    def record(self, entry: dict) -> None:
        if not _valid(entry):
            raise ValueError(f"invalid journal entry: {entry}")
        with self._lock:
            self._save([*self._load(), entry])

    def rollback(self, undo: Callable[[dict], None]) -> None:
        with self._lock:
            for entry in reversed(self._load()):
                try:
                    undo(entry)
                except Exception as e:
                    logger.warning("Undo failed for %s: %s", entry, e)
            self._save([])
