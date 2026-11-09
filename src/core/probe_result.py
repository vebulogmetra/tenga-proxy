"""Результат замера задержки одного сервера: задержка или причина отказа.

Без зависимостей: модель передаётся от пробы через `LatencyRunner` до профиля и
читается интерфейсом обоих тулкитов.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

DETAIL_LIMIT = 300
# Сколько замер ждёт ответа сервера; называется и в подсказке отказа.
PROBE_TIMEOUT_SECONDS = 3
# Сколько замер считается свежим: по нему выбирают сервер без перезамера.
PROBE_FRESH_SECONDS = 30 * 60


def is_fresh(checked_at: int, now: float) -> bool:
    """Замер моложе PROBE_FRESH_SECONDS; время 0 (старый файл) — несвежий."""
    if checked_at <= 0:
        return False
    return now - checked_at < PROBE_FRESH_SECONDS


class ProbeFailure(StrEnum):
    """Почему сервер не прошёл замер. Значения хранятся в профилях."""

    INVALID_CONFIG = "invalid_config"  # параметры не собрались в outbound
    REJECTED = "rejected"  # `xray -test` отверг outbound
    CORE_FAILED = "core_failed"  # пробное ядро не запустилось
    TIMEOUT = "timeout"  # сервер не ответил за время ожидания
    UNREACHABLE = "unreachable"  # 5xx от inbound или обрыв соединения
    BAD_RESPONSE = "bad_response"  # 407 и прочие неуспешные ответы

    @classmethod
    def parse(cls, value: object) -> ProbeFailure | None:
        """Значение из файла; незнакомое (от новой версии) — None."""
        try:
            return cls(value)
        except ValueError:
            return None


def clip_detail(text: str) -> str:
    """Текст ядра или исключения в одну строку, не длиннее DETAIL_LIMIT."""
    flat = " ".join(str(text).split())
    if len(flat) <= DETAIL_LIMIT:
        return flat
    return flat[: DETAIL_LIMIT - 1] + "…"


@dataclass(frozen=True)
class ProbeResult:
    """Итог замера: `latency_ms > 0` при успехе, иначе `failure` с пояснением."""

    latency_ms: int = -1
    failure: ProbeFailure | None = None
    checked_at: int = 0  # unix-время, 0 — неизвестно
    detail: str = ""

    @classmethod
    def ok(cls, latency_ms: int) -> ProbeResult:
        # Ноль на loopback возможен, но «0 мс» читалось бы как «не мерили».
        return cls(latency_ms=max(1, int(latency_ms)), checked_at=int(time.time()))

    @classmethod
    def failed(cls, failure: ProbeFailure, detail: str = "") -> ProbeResult:
        return cls(failure=failure, checked_at=int(time.time()), detail=clip_detail(detail))

    @property
    def succeeded(self) -> bool:
        return self.failure is None and self.latency_ms > 0
