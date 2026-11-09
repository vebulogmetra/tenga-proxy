"""Восстановление сеанса после сна и смены сети."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.main_loop import ImmediateLoop
from src.core.net_recovery import (
    NETWORK_WAIT_SECONDS,
    SETTLE_MS,
    NetworkRecovery,
    RecoveryReason,
)

HOME = ("192.168.1.1", "wlan0")
CAFE = ("10.0.0.1", "wlan0")
ALIVE = SimpleNamespace(proxy_ok=True, server_probed=True)
SILENT = SimpleNamespace(proxy_ok=False, server_probed=True)
CACHED = SimpleNamespace(proxy_ok=False, server_probed=False)


class Harness:
    def __init__(self, *, tun=True, monitoring=True):
        self.loop = ImmediateLoop()
        self.clock = 100.0
        self.session = True
        self.tun = tun
        self.online = True
        self.route = HOME
        self.monitoring = monitoring
        self.events: list[object] = []
        self.recovery = NetworkRecovery(
            loop=self.loop,
            session_active=lambda: self.session,
            tun_session=lambda: self.tun,
            network_available=lambda: self.online,
            fingerprint=lambda: self.route,
            pause_monitor=lambda: self.events.append("pause"),
            resume_monitor=lambda: self.events.append("resume"),
            check_session=self._check,
            reconnect=lambda reason: self.events.append(("reconnect", reason)),
            now=lambda: self.clock,
        )
        self.recovery.remember_fingerprint()

    def _check(self) -> bool:
        self.events.append("check")
        return self.monitoring

    def settle(self) -> None:
        """Пачка сигналов затихла: срабатывает таймер выжидания."""
        intervals = [interval for interval, _fn in self.loop.scheduled]
        assert SETTLE_MS in intervals
        self.loop.fire()


def test_sleep_pauses_the_monitor_and_suspends_failover():
    harness = Harness()

    harness.recovery.on_sleep()

    assert harness.events == ["pause"]
    assert harness.recovery.active


def test_sleep_without_a_session_does_nothing():
    harness = Harness()
    harness.session = False

    harness.recovery.on_sleep()
    harness.recovery.on_resume()

    assert harness.events == []
    assert not harness.recovery.active


def test_resume_in_the_same_network_checks_once_and_finishes_on_success():
    harness = Harness()
    harness.recovery.on_sleep()

    harness.recovery.on_resume()
    assert harness.events == ["pause", "resume", "check"]
    assert harness.recovery.active

    harness.recovery.handle_status(CACHED)  # ручная проверка без запроса — не итог
    assert harness.recovery.active
    harness.recovery.handle_status(ALIVE)

    assert not harness.recovery.active
    assert ("reconnect", RecoveryReason.SLEEP) not in harness.events


def test_failed_check_reconnects_once_with_the_reason():
    harness = Harness()
    harness.recovery.on_sleep()
    harness.recovery.on_resume()

    harness.recovery.handle_status(SILENT)
    harness.recovery.handle_status(SILENT)  # дальше — обычный failover

    assert harness.events.count(("reconnect", RecoveryReason.SLEEP)) == 1
    assert not harness.recovery.active


def test_changed_route_in_tun_reconnects_without_a_check():
    harness = Harness()
    harness.route = CAFE

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == [("reconnect", RecoveryReason.NETWORK)]
    assert harness.recovery.known_fingerprint == CAFE
    assert not harness.recovery.active


def test_changed_route_outside_tun_is_only_checked():
    harness = Harness(tun=False)
    harness.route = CAFE

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == ["check"]


def test_burst_of_network_signals_waits_for_silence():
    harness = Harness()
    harness.route = CAFE

    for _ in range(5):
        harness.recovery.on_network_changed()

    # Каждый сигнал переставляет таймер: в очереди один.
    assert len(harness.loop.scheduled) == 1
    assert harness.events == []
    harness.settle()
    assert harness.events == [("reconnect", RecoveryReason.NETWORK)]


def test_network_change_after_resume_keeps_the_sleep_reason():
    harness = Harness()
    harness.recovery.on_sleep()
    harness.recovery.on_network_changed()  # во сне — не в счёт
    harness.online = False
    harness.recovery.on_resume()
    harness.route = CAFE
    harness.online = True

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events[-1] == ("reconnect", RecoveryReason.SLEEP)


def test_waits_for_the_network_then_gives_up():
    harness = Harness()
    harness.recovery.on_sleep()
    harness.online = False
    harness.route = None

    harness.recovery.on_resume()
    harness.loop.fire()
    assert harness.recovery.active
    assert "check" not in harness.events

    harness.clock += NETWORK_WAIT_SECONDS
    harness.loop.fire()

    assert not harness.recovery.active
    assert harness.events == ["pause", "resume"]
    assert harness.loop.scheduled == []


def test_network_appearing_within_the_window_continues_recovery():
    harness = Harness()
    harness.online = False
    harness.route = None
    harness.recovery.on_network_changed()
    harness.settle()
    assert harness.recovery.active

    harness.online = True
    harness.route = CAFE
    harness.loop.fire()

    assert harness.events == [("reconnect", RecoveryReason.NETWORK)]


def test_a_physical_route_counts_as_network_when_the_monitor_disagrees():
    # NetworkManager говорит «нет сети», пока соседний интерфейс застрял в DHCP.
    harness = Harness()
    harness.online = False
    harness.route = CAFE

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == [("reconnect", RecoveryReason.NETWORK)]


def test_without_monitoring_there_is_nothing_to_check():
    harness = Harness(monitoring=False)

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == ["check"]
    assert not harness.recovery.active


def test_check_that_never_reports_closes_the_window():
    harness = Harness()
    harness.recovery.on_network_changed()
    harness.settle()
    assert harness.recovery.active

    harness.clock += 60
    harness.loop.fire()

    assert not harness.recovery.active


def test_session_closed_during_the_window_stops_recovery():
    harness = Harness()
    harness.online = False
    harness.recovery.on_network_changed()
    harness.settle()

    harness.recovery.cancel()

    assert not harness.recovery.active
    assert harness.recovery.known_fingerprint is None
    assert harness.loop.scheduled == []


def test_unknown_route_is_not_a_change():
    harness = Harness()
    harness.route = None

    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == ["check"]
    assert harness.recovery.known_fingerprint == HOME


def test_failing_route_reader_counts_as_unknown():
    harness = Harness()

    def broken():
        raise OSError("ip")

    harness.recovery._fingerprint = broken
    harness.recovery.on_network_changed()
    harness.settle()

    assert harness.events == ["check"]
