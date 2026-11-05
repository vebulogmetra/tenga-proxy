"""SO_BINDTODEVICE: выводит сокет пробы мимо TUN, не трогая маршруты.

С ядра 5.7 опция доступна без прав, пока сокет не привязан. Если помощник TUN заменил
физический маршрут по умолчанию, connect вернёт ENETUNREACH: это обрабатывает диагностика.
"""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Iterable
from pathlib import Path

from src.sys.linux.vpn import get_default_interface

SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)
SYS_CLASS_NET = Path("/sys/class/net")


def bind_socket(sock: socket.socket, interface: str) -> None:
    sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, interface.encode() + b"\0")


def binding_confirmed() -> bool:
    return True


def _tun_devices() -> list[str]:
    """TUN определяется по ядру, а не по имени: имя интерфейса задаётся в настройках."""
    try:
        return [path.name for path in SYS_CLASS_NET.iterdir() if (path / "tun_flags").exists()]
    except OSError:
        return []


def physical_interface(exclude: Iterable[str] = ()) -> str | None:
    return get_default_interface(exclude=[*exclude, *_tun_devices()])


def active_tunnel_interface() -> str | None:
    """TUN, через который сейчас идёт маршрут по умолчанию; нужно CLI рядом с живым GUI."""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tunnels = set(_tun_devices())
    for line in result.stdout.splitlines():
        parts = line.split()
        if "dev" in parts and parts.index("dev") + 1 < len(parts):
            device = parts[parts.index("dev") + 1]
            if device in tunnels:
                return device
    return None


def interface_kind(interface: str) -> str:
    path = SYS_CLASS_NET / interface
    if (path / "wireless").exists():
        return "WIFI"
    return "ETHERNET" if (path / "device").exists() else "OTHER"


def interface_addresses(interface: str) -> tuple[str, ...]:
    """Адреса глобальной области: для сравнения сети и выбора семейства, в отчёт не идут."""
    try:
        result = subprocess.run(
            ["ip", "-o", "addr", "show", "dev", interface, "scope", "global"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    addresses = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] in ("inet", "inet6"):
            addresses.append(parts[3].split("/")[0])
    return tuple(sorted(addresses))
