"""SO_BINDTODEVICE: выводит сокет пробы мимо TUN, не трогая маршруты.

С ядра 5.7 опция доступна без прав, пока сокет не привязан. Обойти TUN можно, только пока у
интерфейса есть свой маршрут по умолчанию и rp_filter не строгий: это проверяет
`binding_confirmed`.
"""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from src.sys.linux.vpn import get_default_interface

SO_BINDTODEVICE = getattr(socket, "SO_BINDTODEVICE", 25)
SYS_CLASS_NET = Path("/sys/class/net")
PROC_NET_CONF = Path("/proc/sys/net/ipv4/conf")


def socket_binder(interface: str) -> Callable[[socket.socket], None]:
    device = interface.encode() + b"\0"

    def bind(sock: socket.socket) -> None:
        sock.setsockopt(socket.SOL_SOCKET, SO_BINDTODEVICE, device)

    return bind


def _strict_rp_filter(interface: str) -> bool:
    """Действует наибольшее из `all` и интерфейса: 0 выключен, 1 строгий, 2 свободный."""
    values = []
    for name in ("all", interface):
        try:
            values.append(int((PROC_NET_CONF / name / "rp_filter").read_text().strip()))
        except (OSError, ValueError):
            values.append(0)
    return max(values) == 1


def binding_confirmed(interface: str) -> bool:
    """Сокету на интерфейсе есть куда идти и ответы до него дойдут.

    Маршрут: старый помощник заменял маршрут по умолчанию без метрики, и тогда у интерфейса
    своего нет. rp_filter: ответ сервера приходит на интерфейс, а лучший маршрут к серверу
    ведёт в TUN через `0.0.0.0/1`; строгий режим такой пакет отбрасывает, свободный (Ubuntu
    и systemd по умолчанию) пропускает. Только IPv4: IPv6 мимо туннеля в сеансе TUN закрыт
    таблицей `ipv6_only`.
    """
    if _strict_rp_filter(interface):
        return False
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default", "dev", interface],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


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
            ["ip", "-4", "route", "show"],
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
        # Помощник кладёт на TUN половины 0.0.0.0/1 и 128.0.0.0/1, чужой туннель — default.
        if parts[:1] not in (["default"], ["0.0.0.0/1"]):
            continue
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
