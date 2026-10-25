"""Журнал отката: что приложение изменило в сети и как это вернуть.

Пишет его служба Windows и Linux-реализация маршрутов TUN. Запись делается до
изменения, файл переписывается атомарно, поэтому журнал переживает падение
процесса и откатывается при следующем старте. Откат идёт в обратном порядке,
сбой одного шага не останавливает остальные. При загрузке записи проверяются
схемой, которую задаёт владелец журнала: файл лежит на диске, и доверять ему
как коду нельзя.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("tenga.core.net_journal")


class Journal:
    def __init__(self, path: Path, valid: Callable[[object], bool]) -> None:
        self._path = path
        self._valid = valid
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
        valid = [entry for entry in entries if self._valid(entry)]
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
        if not self._valid(entry):
            raise ValueError(f"invalid journal entry: {entry}")
        with self._lock:
            self._save([*self._load(), entry])

    def clear(self) -> None:
        with self._lock:
            self._save([])

    def rollback(self, undo: Callable[[dict], None]) -> None:
        with self._lock:
            for entry in reversed(self._load()):
                try:
                    undo(entry)
                except Exception as e:
                    logger.warning("Undo failed for %s: %s", entry, e)
            self._save([])
