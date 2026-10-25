"""Чего не хватает для режима TUN на Linux. Только проверка, без изменений.

TUN держится на двух правах: xray создаёт интерфейс (`cap_net_admin`, которую
выдаёт `setcap` при установке AppImage), а приложение переключает маршрут по
умолчанию через `sudo -n` — помощником из sudoers или самой `ip`. Без них
подключение падает с невнятной ошибкой ядра или sudo; здесь те же условия
проверяются заранее и описываются словами, с командой для исправления.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from collections.abc import Callable

from src.sys.linux.tun_route import HELPER_PATH

CAP_NET_ADMIN = 12
_VFS_CAP_FLAGS_EFFECTIVE = 0x1


def _sudo_allows(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def has_net_admin(path: str, getxattr: Callable[[str, str], bytes] = os.getxattr) -> bool:
    """Файловая capability `cap_net_admin+ep` у бинарника.

    Формат `security.capability` (vfs_cap_data): magic_etc, затем младшие
    32 бита permitted. Без флага effective программа, которая сама права не
    поднимает (xray так не делает), их не получит.
    """
    try:
        data = getxattr(path, "security.capability")
    except OSError:
        return False
    if len(data) < 8:
        return False
    magic, permitted = struct.unpack_from("<II", data)
    return bool(magic & _VFS_CAP_FLAGS_EFFECTIVE) and bool(permitted & (1 << CAP_NET_ADMIN))


def tun_problems(
    xray_path: str | None,
    *,
    geteuid: Callable[[], int] = os.geteuid,
    getxattr: Callable[[str, str], bytes] = os.getxattr,
    sudo_allows: Callable[[list[str]], bool] = _sudo_allows,
    exists: Callable[[str], bool] = os.path.exists,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Причины, по которым TUN не заработает; пустой список — всё на месте."""
    if geteuid() == 0:
        return []

    problems = []
    if xray_path and not has_net_admin(xray_path, getxattr):
        problems.append(
            "У xray-core нет права cap_net_admin: TUN-интерфейс не создать. "
            f"Выполните: sudo setcap cap_net_admin,cap_net_raw+ep {xray_path}"
        )

    candidates = []
    if exists(HELPER_PATH):
        candidates.append(HELPER_PATH)
    ip = which("ip")
    if ip:
        candidates.append(ip)
    routes_ok = bool(which("sudo")) and any(
        sudo_allows(["sudo", "-n", "-l", command]) for command in candidates
    )
    if not routes_ok:
        problems.append(
            "Маршрут по умолчанию переключается через sudo без пароля, а правила нет. "
            "Установите AppImage командой python cli.py install: она ставит помощника "
            f"{HELPER_PATH} и правило sudoers для него"
        )
    return problems
