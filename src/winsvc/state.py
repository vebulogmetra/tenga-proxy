"""Состояние службы: одно ядро, его маршруты и DNS, и как всё это вернуть.

Методы повторяют вызовы, которые `connection.py` делает на Linux, — фасады
`src/sys/windows` переадресуют их сюда. Каждое изменение сети сначала
записывается в журнал. Откат — при остановке ядра, его падении (замечает
`tick`), пропаже клиента дольше `GRACE_SECONDS` и при старте службы. Все
системные зависимости внедряются: в тестах — подделки.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections import deque

from src import __version__
from src.core.proxy_mode import TUN_DNS_ADDRESS
from src.sys.addresses import resolve_ipv4
from src.sys.windows import netinfo
from src.winsvc import netops, wireguard
from src.winsvc.policy import PolicyError, sanitize_core_config

logger = logging.getLogger("tenga.winsvc.state")

GRACE_SECONDS = 15.0
LOG_BUFFER = 1000
SPLIT_DEFAULT = ("0.0.0.0/1", "128.0.0.0/1")


class ServiceError(RuntimeError):
    """Команду нельзя выполнить; текст уходит в GUI как есть."""


class ServiceState:
    def __init__(
        self,
        *,
        runner,
        net,
        journal,
        clock=time.monotonic,
        resolve=resolve_ipv4,
        adapter_wait: float = 5.0,
    ) -> None:
        self._runner = runner
        self._net = net
        self._journal = journal
        self._clock = clock
        self._resolve = resolve
        self._adapter_wait = adapter_wait
        self._lock = threading.RLock()
        self._log: deque[str] = deque(maxlen=LOG_BUFFER)
        self._expect_running = False
        self._exited = False
        self._gone_since: float | None = None

    # --- команды ---

    def hello(self, version: str) -> dict:
        if version != __version__:
            raise ServiceError(
                f"Версия службы {__version__} не совпадает с приложением {version}: "
                "переустановите Tenga Proxy"
            )
        return {"version": __version__}

    def core_start(self, config: dict) -> dict:
        try:
            sanitized = sanitize_core_config(config)
        except PolicyError as e:
            raise ServiceError(f"Конфигурация отклонена службой: {e}") from e
        with self._lock:
            self._stop_locked()
            ok, error = self._runner.start(sanitized)
            if not ok:
                raise ServiceError(error or "Не удалось запустить xray-core")
            self._expect_running = True
            self._exited = False
        return {}

    def core_stop(self) -> dict:
        with self._lock:
            self._stop_locked()
        return {}

    def core_status(self) -> dict:
        with self._lock:
            log = list(self._log)
            self._log.clear()
            return {"running": self._runner.is_running, "exited": self._exited, "log": log}

    def core_stats(self) -> dict:
        traffic = self._runner.get_traffic()
        return {"upload": traffic.upload, "download": traffic.download}

    def routes_apply(self, tun_name: str, proxy_host: str) -> dict:
        with self._lock:
            tun = self._wait_adapter(tun_name)
            route = netinfo.default_route(self._net.snapshot(), exclude=(tun_name,))
            if route is None:
                raise ServiceError("Не найден маршрут по умолчанию через физический интерфейс")
            proxy_ip = self._resolve(proxy_host)
            if not proxy_ip:
                raise ServiceError(f"Не удалось разрешить адрес прокси: {proxy_host}")

            if not ipaddress.IPv4Address(proxy_ip).is_loopback:
                self._add_route(f"{proxy_ip}/32", route.index, route.nexthop or None)
            for prefix in SPLIT_DEFAULT:
                self._add_route(prefix, tun.index, None)
            return {"proxy_ip": proxy_ip}

    def routes_restore(self) -> dict:
        with self._lock:
            self._rollback()
        return {}

    def dns_apply(self, tun_name: str) -> dict:
        with self._lock:
            tun = self._wait_adapter(tun_name)
            self._net.run(netops.set_dns(tun.index, TUN_DNS_ADDRESS))
            self._net.run(netops.set_metric(tun.index, 1))
            name = self._net.nrpt_add(TUN_DNS_ADDRESS)
            if name is None:
                raise ServiceError("Не удалось добавить правило NRPT")
            self._journal.record({"op": "nrpt.remove", "name": name})
        return {}

    # --- WireGuard ---

    def wireguard_list(self) -> dict:
        return {"tunnels": wireguard.list_tunnels()}

    def wireguard_up(self, name: str) -> dict:
        try:
            command = wireguard.up_command(name)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        if name not in wireguard.list_tunnels():
            raise ServiceError(f"Туннель WireGuard «{name}» не найден")
        if not self._net.run(command):
            raise ServiceError(f"WireGuard не поднял туннель «{name}»")
        return {}

    def wireguard_down(self, name: str) -> dict:
        try:
            command = wireguard.down_command(name)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        if not self._net.run(command):
            raise ServiceError(f"WireGuard не опустил туннель «{name}»")
        return {}

    # --- жизненный цикл ---

    def core_output(self, line: str) -> None:
        with self._lock:
            self._log.append(line)

    def client_connected(self) -> None:
        with self._lock:
            self._gone_since = None

    def client_gone(self) -> None:
        with self._lock:
            self._gone_since = self._clock()

    def tick(self) -> None:
        """Раз в секунду из потока службы: падение ядра и пропавший клиент."""
        with self._lock:
            if self._expect_running and not self._runner.is_running:
                logger.warning("xray-core exited unexpectedly, rolling back")
                self._expect_running = False
                self._exited = True
                self._rollback()
            if (
                self._gone_since is not None
                and self._expect_running
                and self._clock() - self._gone_since >= GRACE_SECONDS
            ):
                logger.info("Client is gone for %.0f s, stopping", GRACE_SECONDS)
                self._stop_locked()
                self._gone_since = None

    def recover(self) -> None:
        """При старте службы: убрать следы прошлой сессии."""
        with self._lock:
            self._net.nrpt_sweep()
            self._rollback()

    # --- внутреннее ---

    def _stop_locked(self) -> None:
        self._expect_running = False
        try:
            self._runner.stop()
        finally:
            self._rollback()

    def _rollback(self) -> None:
        self._journal.rollback(self._net.undo)
        netinfo.invalidate()

    def _add_route(self, prefix: str, index: int, nexthop: str | None) -> None:
        self._journal.record({"op": "route.delete", "prefix": prefix, "index": index})
        if not self._net.run(netops.route_add(prefix, index, nexthop)):
            raise ServiceError(f"Не удалось добавить маршрут {prefix}")

    def _wait_adapter(self, alias: str):
        deadline = self._clock() + self._adapter_wait
        while True:
            adapter = self._net.snapshot().adapter(alias)
            if adapter is not None:
                return adapter
            if self._clock() >= deadline:
                raise ServiceError(f"Адаптер {alias} не появился: ядро не создало TUN")
            netinfo.invalidate()
            time.sleep(0.25)
