"""Сон и смена сети для GTK: logind на системной шине и `Gio.NetworkMonitor`.

Только переводит сигналы в вызовы контроллера (`on_sleep`, `on_resume`,
`on_network_changed`); что делать с сеансом, решает `NetworkRecovery`.
"""

from __future__ import annotations

import logging
from typing import Any

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

logger = logging.getLogger("tenga.ui.system_events")

LOGIN1_NAME = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_MANAGER = "org.freedesktop.login1.Manager"


class SystemEvents:
    """Подписки на logind и монитор сети; `bus` и `monitor` подменяются в тестах."""

    def __init__(self, controller: Any, *, bus: Any = None, monitor: Any = None) -> None:
        self._controller = controller
        self._bus = bus
        self._monitor = monitor
        self._subscription: int | None = None
        self._network_handler: int | None = None

    def start(self) -> None:
        bus = self._bus
        if bus is None:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            except GLib.Error as e:
                # Без системной шины сон не отследить; смена сети всё равно видна.
                logger.info("System bus is unavailable, sleep is not watched: %s", e)
        if bus is not None:
            self._bus = bus
            self._subscription = bus.signal_subscribe(
                LOGIN1_NAME,
                LOGIN1_MANAGER,
                "PrepareForSleep",
                LOGIN1_PATH,
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_prepare_for_sleep,
            )

        if self._monitor is None:
            self._monitor = Gio.NetworkMonitor.get_default()
        self._network_handler = self._monitor.connect("network-changed", self._on_network_changed)

    def stop(self) -> None:
        if self._bus is not None and self._subscription is not None:
            self._bus.signal_unsubscribe(self._subscription)
        self._subscription = None
        if self._monitor is not None and self._network_handler is not None:
            self._monitor.disconnect(self._network_handler)
        self._network_handler = None

    def _on_prepare_for_sleep(self, _bus, _sender, _path, _iface, _signal, parameters) -> None:
        (going_to_sleep,) = parameters.unpack()
        if going_to_sleep:
            self._controller.on_sleep()
        else:
            self._controller.on_resume()

    def _on_network_changed(self, _monitor, _available) -> None:
        self._controller.on_network_changed()
