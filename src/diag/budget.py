"""Бюджет запуска: порт DiagnosticBudget.kt и DiagnosticScheduleSession.kt."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from src.diag.models import DiagnosticRequest


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class DiagnosticBudget:
    """Резервирует весь возможный объём до ввода-вывода; резерв намеренно не возвращается."""

    def __init__(self, max_attempts: int, max_bytes: int):
        if max_attempts <= 0 or max_bytes <= 0:
            raise ValueError("budget must be positive")
        self._max_attempts = max_attempts
        self._max_bytes = max_bytes
        self._attempts = 0
        self._bytes = 0
        self._lock = threading.Lock()

    def reserve(self, payload_bytes: int) -> bool:
        if payload_bytes < 0:
            raise ValueError("payload must not be negative")
        with self._lock:
            if self._attempts >= self._max_attempts:
                return False
            if payload_bytes > self._max_bytes - self._bytes:
                return False
            self._attempts += 1
            self._bytes += payload_bytes
            return True


class ScheduleSession:
    """Один ручной запуск может планировать несколько зависимых фаз с общим бюджетом."""

    def __init__(self, request: DiagnosticRequest, clock: Callable[[], int] = monotonic_ms):
        self.budget = DiagnosticBudget(request.max_attempts, request.max_payload_bytes)
        self._clock = clock
        self._started = clock()
        self._deadline_ms = request.deadline_ms

    def remaining_ms(self) -> int:
        return max(self._deadline_ms - (self._clock() - self._started), 0)
