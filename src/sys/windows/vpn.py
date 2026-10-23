"""Интерфейсы и VPN на Windows.

Интерфейсы, адреса и DNS берутся из снимка сети. VPN — два источника:
встроенные подключения Windows (`ras`) и туннели WireGuard (через службу:
их конфигурации читает только SYSTEM). При совпадении имён выигрывает
встроенное подключение. Прочие клиенты (OpenVPN и т. п.) не управляются, но
их поднятый адаптер с тем же именем профиль использует.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

from src.sys.windows import netinfo, ras, service_client
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.sys.vpn")

# Адаптер WireGuard появляется не сразу после подъёма службы туннеля.
INTERFACE_WAIT_SECONDS = 5.0


def _wireguard_tunnels() -> list[str]:
    try:
        return list(service_client.get_client().call("wireguard.list").get("tunnels", []))
    except ServiceError as e:
        logger.info("WireGuard tunnels are unavailable: %s", e)
        return []


def _wireguard_running(name: str) -> bool:
    from src.sys.windows.powershell import run_json
    from src.winsvc import wireguard

    try:
        service = wireguard.service_name(name)
    except ValueError:
        return False
    status = run_json(f"(Get-Service -Name '{service}' -ErrorAction SilentlyContinue).Status")
    return status.strip() == "Running"


def _wireguard_call(cmd: str, name: str) -> bool:
    try:
        service_client.get_client().call(cmd, name=name)
        return True
    except ServiceError as e:
        logger.warning("%s %s failed: %s", cmd, name, e)
        return False


def _adapter_up(name: str) -> bool:
    adapter = netinfo.snapshot().adapter(name)
    return bool(adapter and adapter.ipv4 and adapter.status == "Up")


def _wait_interface(name: str, timeout: float = INTERFACE_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while True:
        netinfo.invalidate()
        if _adapter_up(name) or time.monotonic() >= deadline:
            return
        time.sleep(0.5)


def list_vpn_connections() -> list[str]:
    return sorted({*ras.connections(), *_wireguard_tunnels()})


def is_vpn_active(connection_name: str) -> bool:
    if not connection_name:
        return False
    known = ras.connections()
    if connection_name in known:
        return known[connection_name]
    return _wireguard_running(connection_name) or _adapter_up(connection_name)


def get_vpn_interface(connection_name: str) -> str | None:
    # И у RAS, и у WireGuard имя интерфейса совпадает с именем подключения.
    # Кэш сбрасывается: вызов идёт сразу после connect_vpn.
    netinfo.invalidate()
    adapter = netinfo.snapshot().adapter(connection_name) if connection_name else None
    return adapter.alias if adapter else None


def get_vpn_interface_ip(interface_name: str) -> str | None:
    adapter = netinfo.snapshot().adapter(interface_name) if interface_name else None
    return adapter.ipv4[0] if adapter and adapter.ipv4 else None


def connect_vpn(connection_name: str) -> bool:
    if not connection_name:
        return False
    if connection_name in ras.connections():
        return ras.connect(connection_name)
    if connection_name in _wireguard_tunnels():
        if not _wireguard_call("wireguard.up", connection_name):
            return False
        _wait_interface(connection_name)
        return True
    logger.warning("VPN connection %s is not managed by Windows or WireGuard", connection_name)
    return False


def disconnect_vpn(connection_name: str) -> bool:
    if not connection_name:
        return False
    if connection_name in ras.connections():
        return ras.disconnect(connection_name)
    if connection_name in _wireguard_tunnels():
        return _wireguard_call("wireguard.down", connection_name)
    return False


def get_vpn_dns_servers(connection_name: str) -> list[str]:
    adapter = netinfo.snapshot().adapter(connection_name) if connection_name else None
    return list(adapter.dns) if adapter else []


def list_network_interfaces() -> list[str]:
    return sorted(adapter.alias for adapter in netinfo.snapshot().adapters)


def get_default_interface(
    vpn_interface: str | None = None, exclude: Iterable[str] = ()
) -> str | None:
    skipped = set(exclude)
    if vpn_interface:
        skipped.add(vpn_interface)
    route = netinfo.default_route(netinfo.snapshot(), exclude=skipped)
    return route.alias if route else None
