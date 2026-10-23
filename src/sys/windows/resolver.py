"""DNS-серверы физического интерфейса Windows (для перехвата DNS в TUN)."""

from __future__ import annotations

from src.sys.addresses import usable_ipv4
from src.sys.windows import netinfo


def system_dns_servers(interface: str) -> list[str]:
    adapter = netinfo.snapshot().adapter(interface)
    if adapter is None:
        return []
    servers = [usable_ipv4(server) for server in adapter.dns]
    return [server for server in servers if server]
