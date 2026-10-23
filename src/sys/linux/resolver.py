"""DNS-серверы, которыми система пользуется на физическом интерфейсе.

Нужны при перехвате DNS в режиме TUN: ядро не может спрашивать «системный
резолвер» (`localhost`) — его запрос вернулся бы в TUN и был бы перехвачен
снова. Поэтому настоящие серверы сети называются адресами.
"""

from __future__ import annotations

import ipaddress
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("tenga.sys.resolver")

RESOLV_CONF = Path("/etc/resolv.conf")


def _usable_ipv4(value: str) -> str | None:
    """IPv4-адрес настоящего сервера; loopback — заглушка локального резолвера."""
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback:
        return None
    return str(address)


def link_dns_servers(interface: str) -> list[str]:
    """Серверы интерфейса по данным systemd-resolved (`resolvectl dns <iface>`)."""
    try:
        result = subprocess.run(
            ["resolvectl", "dns", interface],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    # Строка вида «Link 2 (wlp1s0): 192.168.0.1 fe80::1%2».
    _, _, tail = result.stdout.partition("):")
    servers = [_usable_ipv4(token) for token in tail.split()]
    return [server for server in servers if server]


def resolv_conf_servers(path: Path | None = None) -> list[str]:
    """Серверы из resolv.conf, кроме локальных заглушек."""
    try:
        lines = (path or RESOLV_CONF).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    servers = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            server = _usable_ipv4(parts[1])
            if server:
                servers.append(server)
    return servers


def system_dns_servers(interface: str) -> list[str]:
    """Настоящие DNS-серверы сети: интерфейса, а без systemd-resolved — из resolv.conf."""
    return link_dns_servers(interface) or resolv_conf_servers()
