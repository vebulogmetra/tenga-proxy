"""xray-core на Windows: TUN — в службе, остальное — в процессе GUI.

`WindowsXrayManager` стоит на месте `XrayManager` в `AppContext` и выбирает,
кто запустит конфиг: TUN-интерфейс создать без прав администратора нельзя.
Снаружи он неотличим от `XrayManager` по тем методам, которыми пользуется
приложение (`start`, `stop`, `reload_config`, `is_running`, `get_traffic`,
`binary_path`, `_check_process_alive`).
"""

from __future__ import annotations

import logging

from src.core.proxy_mode import has_tun_inbound
from src.core.xray_manager import TrafficStats, core_output_logger
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.sys.core_runner")


class ServiceCoreRunner:
    def __init__(self, client=None, log_sink=None) -> None:
        if client is None:
            from src.sys.windows.service_client import get_client

            client = get_client()
        self._client = client
        self._log_sink = log_sink or core_output_logger().info
        self._on_stop = None

    def start(self, config: dict) -> tuple[bool, str]:
        try:
            self._client.call("core.start", config=config)
            return True, ""
        except ServiceError as e:
            return False, str(e)

    def stop(self) -> tuple[bool, str]:
        try:
            self._client.call("core.stop")
        except ServiceError as e:
            logger.warning("Service stop failed: %s", e)
        if self._on_stop:
            self._on_stop()
        return True, ""

    @property
    def is_running(self) -> bool:
        try:
            status = self._client.call("core.status")
        except ServiceError:
            return False
        for line in status.get("log", []):
            self._log_sink(line)
        return bool(status.get("running"))

    def get_traffic(self) -> TrafficStats:
        try:
            stats = self._client.call("core.stats")
        except ServiceError:
            return TrafficStats()
        return TrafficStats(int(stats.get("upload", 0)), int(stats.get("download", 0)))

    def set_on_stop_callback(self, callback) -> None:
        self._on_stop = callback


class WindowsXrayManager:
    def __init__(self, local, service: ServiceCoreRunner) -> None:
        self._local = local
        self._service = service
        self._active = None

    @property
    def binary_path(self) -> str:
        return self._local.binary_path

    def get_version(self):
        return self._local.get_version()

    def start(self, config: dict) -> tuple[bool, str]:
        self.stop()
        backend = self._service if has_tun_inbound(config) else self._local
        ok, error = backend.start(config)
        self._active = backend if ok else None
        return ok, error

    def stop(self) -> tuple[bool, str]:
        active, self._active = self._active, None
        if active is None:
            return True, ""
        return active.stop()

    def reload_config(self, config: dict) -> tuple[bool, str]:
        return self.start(config)

    @property
    def is_running(self) -> bool:
        return self._active is not None and self._active.is_running

    def _check_process_alive(self) -> bool:
        # Имя повторяет XrayManager: его зовёт ConnectionMonitor.
        return self.is_running

    def get_traffic(self) -> TrafficStats:
        return self._active.get_traffic() if self._active is not None else TrafficStats()

    def set_on_stop_callback(self, callback) -> None:
        self._local.set_on_stop_callback(callback)
        self._service.set_on_stop_callback(callback)
