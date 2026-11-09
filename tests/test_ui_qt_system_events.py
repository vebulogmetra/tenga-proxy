"""Сигналы сети, logind и питания доходят до контроллера в Qt."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from src.core.main_loop import ImmediateLoop
from src.ui.qt import system_events
from src.ui.qt.system_events import LOGIN1_MANAGER, LOGIN1_PATH, SystemEvents

pytestmark = pytest.mark.qt


class FakeNetwork(QObject):
    reachabilityChanged = Signal(object)
    transportMediumChanged = Signal(object)


class FakeBus:
    def __init__(self, connected=True):
        self.connected = connected
        self.connections = []

    def isConnected(self):
        return self.connected

    def connect(self, service, path, interface, name, receiver, slot):
        self.connections.append((service, path, interface, name, slot))
        self.receiver = receiver
        return True


class Target:
    def __init__(self):
        self.events = []

    def on_sleep(self):
        self.events.append("sleep")

    def on_resume(self):
        self.events.append("resume")

    def on_network_changed(self):
        self.events.append("network")


def test_network_and_logind_signals_reach_the_controller(qapp, monkeypatch):
    subscribed = []
    monkeypatch.setattr(
        system_events.power_events, "subscribe", lambda *args: subscribed.append(args)
    )
    network, bus, target = FakeNetwork(), FakeBus(), Target()
    events = SystemEvents(target, ImmediateLoop(), network=network, bus=bus)
    events.start()

    network.reachabilityChanged.emit(None)
    network.transportMediumChanged.emit(None)
    bus.receiver.prepare_for_sleep(True)
    bus.receiver.prepare_for_sleep(False)

    assert target.events == ["network", "network", "sleep", "resume"]
    assert bus.connections[0][:4] == (
        "org.freedesktop.login1",
        LOGIN1_PATH,
        LOGIN1_MANAGER,
        "PrepareForSleep",
    )
    # Сон пришёл по шине: системная подписка не нужна.
    assert subscribed == []

    events.stop()
    network.reachabilityChanged.emit(None)
    assert target.events.count("network") == 2


def test_without_a_system_bus_power_events_come_from_the_system(qapp, monkeypatch):
    calls = []

    def subscribe(on_sleep, on_resume, dispatch):
        calls.append("subscribe")
        dispatch(on_sleep)
        dispatch(on_resume)
        return "handle"

    monkeypatch.setattr(system_events.power_events, "subscribe", subscribe)
    monkeypatch.setattr(
        system_events.power_events, "unsubscribe", lambda handle: calls.append(handle)
    )
    target = Target()
    events = SystemEvents(target, ImmediateLoop(), network=FakeNetwork(), bus=FakeBus(False))

    events.start()
    events.stop()

    assert target.events == ["sleep", "resume"]
    assert calls == ["subscribe", "handle"]
