"""IP_UNICAST_IF: выводит сокет пробы на нужный адаптер.

Физический маршрут по умолчанию служба не трогает (на TUN ложатся `0.0.0.0/1` и
`128.0.0.0/1`), поэтому привязка подтверждена, когда маршрут по умолчанию ведёт на адаптер.
Сама опция под настоящим TUN проверяется в `tests/integration/`.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable, Iterable

from src.sys.windows import netinfo

IP_UNICAST_IF = 31
IPV6_UNICAST_IF = 31


def socket_binder(interface: str) -> Callable[[socket.socket], None]:
    """Адаптер определяется один раз: снимок сети требует обхода адаптеров, а сокетов сотни."""
    adapter = netinfo.snapshot().adapter(interface)

    def bind(sock: socket.socket) -> None:
        if adapter is None:
            raise OSError(f"adapter {interface} is gone")
        if sock.family == socket.AF_INET6:
            # У IPv6 порядок байт хостовый, у IPv4 — сетевой.
            sock.setsockopt(socket.IPPROTO_IPV6, IPV6_UNICAST_IF, adapter.index)
        else:
            sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, struct.pack("!I", adapter.index))

    return bind


def socket_mark() -> int | None:
    """Таблицы nftables на Windows нет: метка не нужна."""
    return None


def binding_confirmed(interface: str) -> bool:
    route = netinfo.default_route(netinfo.snapshot())
    return route is not None and route.alias == interface


def physical_interface(exclude: Iterable[str] = ()) -> str | None:
    route = netinfo.default_route(netinfo.snapshot(), exclude)
    return route.alias if route else None


def active_tunnel_interface() -> str | None:
    snapshot = netinfo.snapshot()
    halves = [
        route
        for route in snapshot.routes
        if route.prefix == netinfo.SPLIT_PREFIX and netinfo.is_tunnel(snapshot.adapter(route.alias))
    ]
    if halves:
        return min(halves, key=lambda route: route.metric).alias
    # Чужой туннель, забравший маршрут по умолчанию целиком.
    whole = [route for route in snapshot.routes if route.prefix == netinfo.DEFAULT_PREFIX]
    best = min(whole, key=lambda route: route.metric, default=None)
    if best is None or not netinfo.is_tunnel(snapshot.adapter(best.alias)):
        return None
    return best.alias


def interface_kind(interface: str) -> str:
    adapter = netinfo.snapshot().adapter(interface)
    description = adapter.description.lower() if adapter else ""
    if "wi-fi" in description or "wireless" in description or "802.11" in description:
        return "WIFI"
    return "ETHERNET" if "ethernet" in description or "gbe" in description else "OTHER"


def interface_addresses(interface: str) -> tuple[str, ...]:
    adapter = netinfo.snapshot().adapter(interface)
    return tuple(sorted(adapter.ipv4)) if adapter else ()
