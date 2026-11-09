"""Сон и смена сети для Qt: `QNetworkInformation`, logind через QtDBus, питание Windows.

Только переводит сигналы в вызовы контроллера (`on_sleep`, `on_resume`,
`on_network_changed`); что делать с сеансом, решает `NetworkRecovery`. ОС здесь
не проверяется: на Windows нет системной шины и QtDBus, на Linux системная
подписка на питание пустая — каждая часть просто не включится там, где её нет.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import SLOT, QObject, Slot
from PySide6.QtNetwork import QNetworkInformation

from src.sys import power_events

logger = logging.getLogger("tenga.ui.qt.system_events")

LOGIN1_NAME = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_MANAGER = "org.freedesktop.login1.Manager"


class SystemEvents(QObject):
    """Подписки на сеть и сон; `network` и `bus` подменяются в тестах."""

    def __init__(self, target: Any, loop: Any, *, network: Any = None, bus: Any = None) -> None:
        super().__init__()
        self._target = target
        self._loop = loop
        self._network = network
        self._bus = bus
        self._power: object | None = None
        self._logind = False

    def start(self) -> None:
        network = self._network if self._network is not None else QNetworkInformation.instance()
        if network is not None:
            self._network = network
            network.reachabilityChanged.connect(self._network_changed)
            network.transportMediumChanged.connect(self._network_changed)
        else:
            logger.info("QNetworkInformation has no backend: network changes are not watched")

        self._logind = self._watch_logind()
        if not self._logind:
            self._power = power_events.subscribe(
                self._target.on_sleep, self._target.on_resume, self._loop.dispatch
            )

    def stop(self) -> None:
        if self._network is not None:
            for signal in (self._network.reachabilityChanged, self._network.transportMediumChanged):
                try:
                    signal.disconnect(self._network_changed)
                except (RuntimeError, TypeError):
                    pass
        power_events.unsubscribe(self._power)
        self._power = None

    def _watch_logind(self) -> bool:
        bus = self._bus
        if bus is None:
            try:
                from PySide6.QtDBus import QDBusConnection
            except ImportError:
                return False
            bus = QDBusConnection.systemBus()
        if not bus.isConnected():
            return False
        return bool(
            bus.connect(
                LOGIN1_NAME,
                LOGIN1_PATH,
                LOGIN1_MANAGER,
                "PrepareForSleep",
                self,
                SLOT("prepare_for_sleep(bool)"),
            )
        )

    @Slot(bool)
    def prepare_for_sleep(self, going_to_sleep: bool) -> None:
        if going_to_sleep:
            self._target.on_sleep()
        else:
            self._target.on_resume()

    def _network_changed(self, *_args) -> None:
        self._target.on_network_changed()
