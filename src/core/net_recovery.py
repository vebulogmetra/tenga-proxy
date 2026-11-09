"""Восстановление сеанса после сна и смены сети.

Без тулкита: события приходят от оболочки (logind, `WM_POWERBROADCAST`,
`Gio.NetworkMonitor`, `QNetworkInformation`), а монитор, проверка, отпечаток
сети и переподключение передаются снаружи. Правило одно с failover: пока
виновата сеть, а не сервер, сервер не меняется.

Ход восстановления:

1. Сон — монитор на паузе, failover проверки не считает.
2. Пробуждение или смена сети (после 3 с тишины) — окно до 30 с ждёт сеть.
3. Сеть есть — сравнивается отпечаток (шлюз и интерфейс маршрута по умолчанию):
   в TUN другой отпечаток значит, что маршрут до сервера ведёт в никуда, и сеанс
   переподключается сразу. Иначе — одна внеочередная проверка, при неудаче одно
   переподключение; дальше работает обычный failover.
4. Сети нет 30 с — окно закрывается, ничего не делается: монитор покажет
   «нет сети», а failover без сети не переключает.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

logger = logging.getLogger("tenga.core.net_recovery")

# Сигналы сети приходят пачками: смена Wi-Fi — это пропажа, появление и смена DNS.
SETTLE_MS = 3000
# Сколько ждать сеть после пробуждения или смены сети.
NETWORK_WAIT_SECONDS = 30
POLL_MS = 1000
# Сколько ждать итога внеочередной проверки монитора.
CHECK_WAIT_SECONDS = 30

Fingerprint = tuple[str, str]
BackgroundFn = Callable[[Callable[[], Any], Callable[[Any], None]], None]


class RecoveryReason(StrEnum):
    SLEEP = "sleep"
    NETWORK = "network"


class _Phase(StrEnum):
    IDLE = "idle"
    ASLEEP = "asleep"
    SETTLING = "settling"  # пачка сигналов сети: ждём тишины
    WAITING = "waiting"  # ждём, когда появится сеть
    FINGERPRINT = "fingerprint"  # читаем маршрут по умолчанию
    CHECKING = "checking"  # ждём итога внеочередной проверки


def _call_now(fn: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
    on_done(fn())


class NetworkRecovery:
    """Решает, что делать с сеансом после сна и смены сети."""

    def __init__(
        self,
        *,
        loop: Any,
        session_active: Callable[[], bool],
        tun_session: Callable[[], bool],
        network_available: Callable[[], bool],
        fingerprint: Callable[[], Fingerprint | None],
        pause_monitor: Callable[[], None],
        resume_monitor: Callable[[], None],
        check_session: Callable[[], bool],
        reconnect: Callable[[RecoveryReason], None],
        background: BackgroundFn = _call_now,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loop = loop
        self._session_active = session_active
        self._tun_session = tun_session
        self._network_available = network_available
        self._fingerprint = fingerprint
        self._pause_monitor = pause_monitor
        self._resume_monitor = resume_monitor
        self._check_session = check_session
        self._reconnect = reconnect
        self._background = background
        self._now = now

        self._phase = _Phase.IDLE
        self._reason = RecoveryReason.NETWORK
        self._monitor_paused = False
        self._timer: object | None = None
        self._deadline = 0.0
        self._generation = 0
        self._known: Fingerprint | None = None

    # --- состояние ---

    @property
    def active(self) -> bool:
        """Идёт восстановление: неудачные проверки говорят о сети, а не о сервере."""
        return self._phase is not _Phase.IDLE

    @property
    def phase(self) -> str:
        return str(self._phase)

    @property
    def known_fingerprint(self) -> Fingerprint | None:
        return self._known

    def remember_fingerprint(self) -> None:
        """Запомнить сеть, в которой поднят сеанс; зовётся после подключения."""
        generation = self._generation

        def store(value: Fingerprint | None) -> None:
            # Сеть успела смениться, пока читался маршрут: решит восстановление.
            if generation == self._generation and value is not None:
                self._known = value

        self._read_fingerprint(store)

    # --- события оболочки ---

    def on_sleep(self) -> None:
        if not self._session_active():
            return
        logger.info("System is going to sleep: pausing the monitor")
        self._cancel_timer()
        self._generation += 1
        self._phase = _Phase.ASLEEP
        if not self._monitor_paused:
            self._monitor_paused = True
            self._pause_monitor()

    def on_resume(self) -> None:
        if self._phase is _Phase.IDLE and not self._session_active():
            return
        logger.info("System resumed: waiting for the network")
        self._open_window(RecoveryReason.SLEEP)

    def on_network_changed(self) -> None:
        if self._phase is _Phase.ASLEEP:
            # Сеть меняется и при засыпании; разберёмся после пробуждения.
            return
        if self._phase is _Phase.IDLE and not self._session_active():
            return
        if self._phase is _Phase.IDLE:
            # Уже идущее восстановление после сна так и остаётся «после сна».
            self._reason = RecoveryReason.NETWORK
        self._cancel_timer()
        self._generation += 1
        self._phase = _Phase.SETTLING
        self._timer = self._loop.schedule(SETTLE_MS, self._settled)

    def handle_status(self, status: Any) -> None:
        """Итог проверки монитора; ждём его только после внеочередной проверки."""
        if self._phase is not _Phase.CHECKING or not getattr(status, "server_probed", False):
            return
        if status.proxy_ok:
            logger.info("Session survived the network change")
            self._finish()
            return
        logger.warning("Session check failed after %s: reconnecting", self._reason)
        reason = self._reason
        self._finish()
        self._reconnect(reason)

    def cancel(self) -> None:
        """Сеанс закрыт: восстанавливать нечего."""
        self._finish()
        self._known = None

    # --- ход восстановления ---

    def _settled(self) -> bool:
        self._timer = None
        self._open_window(self._reason)
        return False

    def _open_window(self, reason: RecoveryReason) -> None:
        self._cancel_timer()
        self._generation += 1
        self._reason = reason
        if not self._session_active():
            self._finish()
            return
        self._phase = _Phase.WAITING
        self._deadline = self._now() + NETWORK_WAIT_SECONDS
        if not self._poll_network():
            return
        self._timer = self._loop.schedule(POLL_MS, self._poll_network)

    def _poll_network(self) -> bool:
        """True — ждать дальше; так же отвечает таймеру главного цикла."""
        if self._phase is not _Phase.WAITING:
            self._timer = None
            return False
        if self._network_available():
            self._timer = None
            self._compare_fingerprint()
            return False
        if self._now() >= self._deadline:
            logger.info("No network within %d s: leaving the session as is", NETWORK_WAIT_SECONDS)
            self._timer = None
            self._finish()
            return False
        return True

    def _compare_fingerprint(self) -> None:
        if not self._session_active():
            self._finish()
            return
        self._phase = _Phase.FINGERPRINT
        generation = self._generation

        def compared(current: Fingerprint | None) -> None:
            if generation != self._generation or self._phase is not _Phase.FINGERPRINT:
                return
            known = self._known
            if current is not None:
                self._known = current
            changed = current is not None and known is not None and current != known
            if changed and self._tun_session():
                # Маршрут до сервера привязан к прежнему шлюзу: проверка не нужна.
                logger.warning("Default route changed %s -> %s: reconnecting", known, current)
                reason = self._reason
                self._finish()
                self._reconnect(reason)
                return
            self._start_check()

        self._read_fingerprint(compared)

    def _start_check(self) -> None:
        self._resume_if_paused()
        if not self._check_session():
            # Мониторинг выключен: проверить нечем, остаётся обычный ход.
            self._finish()
            return
        self._phase = _Phase.CHECKING
        self._deadline = self._now() + CHECK_WAIT_SECONDS
        self._timer = self._loop.schedule(POLL_MS, self._wait_check)

    def _wait_check(self) -> bool:
        if self._phase is not _Phase.CHECKING:
            self._timer = None
            return False
        if self._now() >= self._deadline:
            self._timer = None
            self._finish()
            return False
        return True

    def _finish(self) -> None:
        self._cancel_timer()
        self._generation += 1
        self._phase = _Phase.IDLE
        self._resume_if_paused()

    def _resume_if_paused(self) -> None:
        if self._monitor_paused:
            self._monitor_paused = False
            if self._session_active():
                self._resume_monitor()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._loop.cancel(self._timer)
            self._timer = None

    def _read_fingerprint(self, on_done: Callable[[Fingerprint | None], None]) -> None:
        def read() -> Fingerprint | None:
            try:
                return self._fingerprint()
            except Exception as e:
                logger.debug("Could not read the default route: %s", e)
                return None

        self._background(read, on_done)
