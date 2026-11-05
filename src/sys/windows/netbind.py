"""IP_UNICAST_IF: выводит сокет пробы на нужный адаптер; проверяется на живой Windows.

Пока проверки нет, `binding_confirmed` возвращает False, и прямые пробы под TUN не идут:
лучше честный пропуск, чем отчёт о туннеле под видом прямого пути.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable, Iterable

from src.sys.windows import netinfo

IP_UNICAST_IF = 31
IPV6_UNICAST_IF = 31


def socket_binder(interface: str) -> Callable[[socket.socket], None]:
    """Адаптер определяется один раз: снимок сети — это запуск PowerShell, а сокетов сотни."""
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


def binding_confirmed(interface: str) -> bool:
    return False


def physical_interface(exclude: Iterable[str] = ()) -> str | None:
    route = netinfo.default_route(netinfo.snapshot(), exclude)
    return route.alias if route else None


def active_tunnel_interface() -> str | None:
    snapshot = netinfo.snapshot()
    best = min(snapshot.routes, key=lambda route: route.metric, default=None)
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
