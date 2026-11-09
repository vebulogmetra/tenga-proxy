"""Сигналы logind и монитора сети доходят до контроллера (GTK, без дисплея)."""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")

from gi.repository import GLib

from src.ui.system_events import LOGIN1_MANAGER, LOGIN1_PATH, SystemEvents


class FakeBus:
    def __init__(self):
        self.subscriptions = {}
        self.unsubscribed = []

    def signal_subscribe(self, sender, interface, member, path, arg0, flags, callback):
        self.subscriptions[(sender, interface, member, path)] = callback
        return 7

    def signal_unsubscribe(self, subscription_id):
        self.unsubscribed.append(subscription_id)

    def emit_prepare_for_sleep(self, going):
        callback = self.subscriptions[
            ("org.freedesktop.login1", LOGIN1_MANAGER, "PrepareForSleep", LOGIN1_PATH)
        ]
        callback(
            self,
            ":1.1",
            LOGIN1_PATH,
            LOGIN1_MANAGER,
            "PrepareForSleep",
            GLib.Variant("(b)", (going,)),
        )


class FakeMonitor:
    def __init__(self):
        self.handlers = {}
        self.disconnected = []

    def connect(self, signal, handler):
        self.handlers[signal] = handler
        return 3

    def disconnect(self, handler_id):
        self.disconnected.append(handler_id)


class Target:
    def __init__(self):
        self.events = []

    def on_sleep(self):
        self.events.append("sleep")

    def on_resume(self):
        self.events.append("resume")

    def on_network_changed(self):
        self.events.append("network")


def test_logind_and_network_signals_reach_the_controller():
    bus, monitor, target = FakeBus(), FakeMonitor(), Target()
    events = SystemEvents(target, bus=bus, monitor=monitor)
    events.start()

    bus.emit_prepare_for_sleep(True)
    bus.emit_prepare_for_sleep(False)
    monitor.handlers["network-changed"](monitor, True)

    assert target.events == ["sleep", "resume", "network"]

    events.stop()
    assert bus.unsubscribed == [7]
    assert monitor.disconnected == [3]
