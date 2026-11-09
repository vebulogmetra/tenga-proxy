"""Автопереключение на другой профиль группы, когда сервер перестал отвечать.

Без GTK: решение принимается по статусам монитора, а подключение и уведомление
передаются снаружи. Источник вердикта — сетевая проба через служебный inbound,
поэтому «сервер молчит» здесь значит именно сервер, а не правила маршрутизации.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Collection, Sequence
from typing import Any

from src.core.probe_result import is_fresh

logger = logging.getLogger("tenga.core.failover")

# Сколько не возвращаться к профилю, который только что перестал отвечать.
RECENT_FAILURE_TTL_SECONDS = 15 * 60
# Фоновый перезамер группы активного сервера при включённом автопереключении.
AUTO_REPROBE_MINUTES = 15
AUTO_REPROBE_LIMIT = 30


def rank_candidates(
    profiles: Sequence[Any], *, excluded: Collection[int] = (), now: float | None = None
) -> list[Any]:
    """Профили в порядке выбора: свежие измеренные по задержке, затем несвежие.

    Затем непроверенные, в порядке списка: про них ничего не известно, а
    измеренный хотя бы отвечал. Отказавшие при замере — в последнюю очередь:
    сервер, который не ответил, не становится лучше от прошедшего времени.
    """
    moment = time.time() if now is None else now
    candidates = [profile for profile in profiles if profile.id not in excluded]
    failed = [p for p in candidates if getattr(p, "probe_failure", None) is not None]
    rest = [p for p in candidates if getattr(p, "probe_failure", None) is None]
    measured = sorted(
        (profile for profile in rest if profile.latency_ms > 0),
        key=lambda profile: profile.latency_ms,
    )
    fresh = [p for p in measured if is_fresh(int(getattr(p, "checked_at", 0) or 0), moment)]
    fresh_ids = {id(p) for p in fresh}
    stale = [p for p in measured if id(p) not in fresh_ids]
    unmeasured = [profile for profile in rest if profile.latency_ms <= 0]
    return fresh + stale + unmeasured + failed


def pick_candidate(
    profiles: Sequence[Any], *, excluded: Collection[int], now: float | None = None
) -> Any | None:
    """Профиль, на который переключаться: первый по `rank_candidates`."""
    ordered = rank_candidates(profiles, excluded=excluded, now=now)
    return ordered[0] if ordered else None


def reprobe_targets(
    profiles: Sequence[Any], *, active_id: int, limit: int, now: float | None = None
) -> list[int]:
    """Кого перемерять в фоне: активный, затем по `rank_candidates`, не больше `limit`.

    Большая подписка перемеряется не целиком: фоновая работа не растёт вместе с ней.
    """
    ordered = rank_candidates(profiles, excluded={active_id}, now=now)
    ids = [profile.id for profile in profiles if profile.id == active_id]
    ids.extend(profile.id for profile in ordered)
    return ids[: max(0, limit)]


class FailoverController:
    """Считает неудачные проверки подряд и переключает профиль по порогу."""

    def __init__(
        self,
        context: Any,
        *,
        switch_to: Callable[[int], None],
        notify: Callable[[str], None],
        network_available: Callable[[], bool] = lambda: True,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._context = context
        self._switch_to = switch_to
        self._notify = notify
        self._network_available = network_available
        self._now = now
        self._profile_id = -1
        self._failures = 0
        self._exhausted = False
        self._failed_at: dict[int, float] = {}

    def handle_status(self, _previous: Any, status: Any) -> None:
        """Принять результат очередной проверки монитора (главный цикл)."""
        settings = self._context.config.monitoring
        state = self._context.proxy_state

        if not settings.failover_enabled or not state.is_running:
            self._reset(-1)
            return

        # Ручная проверка повторяет прошлый вердикт без запроса к серверу.
        if not status.server_probed:
            return

        current = state.started_profile_id
        if current != self._profile_id:
            # Подключён другой профиль — вручную или нашим же переключением.
            self._reset(current)

        if status.proxy_ok:
            self._failures = 0
            self._exhausted = False
            return

        if not self._network_available():
            # Сети нет вовсе: сервер тут ни при чём, перебирать профили незачем.
            self._failures = 0
            return

        self._failures += 1
        if self._failures < max(1, settings.failover_threshold):
            return

        self._failures = 0
        self._switch_from(current)

    def _reset(self, profile_id: int) -> None:
        self._profile_id = profile_id
        self._failures = 0
        self._exhausted = False

    def _switch_from(self, failed_id: int) -> None:
        profiles = self._context.profiles
        failed = profiles.get_profile(failed_id)
        if failed is None:
            return

        now = self._now()
        self._failed_at[failed_id] = now
        recent = {
            profile_id
            for profile_id, failed_at in self._failed_at.items()
            if now - failed_at < RECENT_FAILURE_TTL_SECONDS
        }

        candidate = pick_candidate(profiles.get_profiles_in_group(failed.group_id), excluded=recent)
        if candidate is None:
            if not self._exhausted:
                self._exhausted = True
                logger.warning("Failover: no candidates left in group %s", failed.group_id)
                self._notify(f"«{failed.name}» не отвечает, других рабочих серверов в группе нет")
            return

        logger.warning("Failover: switching from profile %s to %s", failed_id, candidate.id)
        self._notify(f"«{failed.name}» не отвечает — переключаюсь на «{candidate.name}»")
        self._switch_to(candidate.id)
