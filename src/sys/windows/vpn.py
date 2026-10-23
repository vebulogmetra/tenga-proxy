"""Интерфейсы и VPN на Windows.

Интерфейсы, адреса и DNS берутся из снимка сети. Управление VPN-подключениями
(RAS, WireGuard) появится в фазе 4 порта; до тех пор список пуст, а подключение
отвечает отказом, и профиль работает без VPN — как на Linux без NetworkManager.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.sys.windows import netinfo

logger = logging.getLogger("tenga.sys.vpn")


def list_vpn_connections() -> list[str]:
    return []


def is_vpn_active(connection_name: str) -> bool:
    return False


def get_vpn_interface(connection_name: str) -> str | None:
    return None


def get_vpn_interface_ip(interface_name: str) -> str | None:
    adapter = netinfo.snapshot().adapter(interface_name) if interface_name else None
    return adapter.ipv4[0] if adapter and adapter.ipv4 else None


def connect_vpn(connection_name: str) -> bool:
    logger.warning("VPN connections are not supported on Windows yet: %s", connection_name)
    return False


def disconnect_vpn(connection_name: str) -> bool:
    return False


def get_vpn_dns_servers(connection_name: str) -> list[str]:
    return []


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
