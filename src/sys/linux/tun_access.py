"""Чего не хватает для режима TUN на Linux. Только проверка, без изменений.

TUN держится на двух правах: xray создаёт интерфейс (`cap_net_admin`, которую
выдаёт `setcap` в postinst deb-пакета), а приложение переключает маршрут по
умолчанию через `sudo -n` — помощником из sudoers или самой `ip`. Без них
подключение падает с невнятной ошибкой ядра или sudo; здесь те же условия
проверяются заранее и описываются словами, с командой для исправления. Сюда же
входит таблица nftables, которой приложение закрывает трафик мимо туннеля.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from collections.abc import Callable

from src.sys.linux.tun_route import HELPER_PATH

# У обычного пользователя /usr/sbin может не быть в PATH, а у sudo он есть всегда.
NFT_PATH = "/usr/sbin/nft"
NO_NFT = (
    "Нет nftables: без него не закрыт IPv6 и не работает блокировка трафика при обрыве. "
    "Выполните: sudo apt install nftables"
)
OLD_HELPER = (
    "Установленный помощник tun-route-helper не умеет закрывать трафик: "
    "обновите его командой sudo apt install --reinstall tenga-proxy"
)

CAP_NET_ADMIN = 12
_VFS_CAP_FLAGS_EFFECTIVE = 0x1


def _sudo_allows(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _helper_features() -> set[str]:
    """Что умеет установленный помощник; у старого такого действия нет."""
    try:
        result = subprocess.run(
            ["sudo", "-n", HELPER_PATH, "features"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(result.stdout.split()) if result.returncode == 0 else set()


def has_net_admin(path: str, getxattr: Callable[[str, str], bytes] | None = None) -> bool:
    """Файловая capability `cap_net_admin+ep` у бинарника.

    Формат `security.capability` (vfs_cap_data): magic_etc, затем младшие
    32 бита permitted. Без флага effective программа, которая сама права не
    поднимает (xray так не делает), их не получит.
    """
    try:
        data = (getxattr or os.getxattr)(path, "security.capability")
    except OSError:
        return False
    if len(data) < 8:
        return False
    magic, permitted = struct.unpack_from("<II", data)
    return bool(magic & _VFS_CAP_FLAGS_EFFECTIVE) and bool(permitted & (1 << CAP_NET_ADMIN))


def tun_problems(
    xray_path: str | None,
    *,
    geteuid: Callable[[], int] | None = None,
    getxattr: Callable[[str, str], bytes] | None = None,
    sudo_allows: Callable[[list[str]], bool] = _sudo_allows,
    exists: Callable[[str], bool] = os.path.exists,
    which: Callable[[str], str | None] = shutil.which,
    helper_features: Callable[[], set[str]] = _helper_features,
) -> list[str]:
    """Причины, по которым TUN не заработает; пустой список — всё на месте."""
    problems = []
    if not which("nft") and not exists(NFT_PATH):
        problems.append(NO_NFT)

    # os.geteuid и os.getxattr есть только на POSIX: берутся при вызове, чтобы
    # модуль импортировался и на Windows, где его проверяют тесты.
    if (geteuid or os.geteuid)() == 0:
        return problems

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
            f"Пакет tenga-proxy разрешает помощника {HELPER_PATH} группе sudo: "
            "добавьте пользователя в группу и перезайдите в сеанс. Если пакет "
            "стоит, а правила нет: sudo apt install --reinstall tenga-proxy"
        )
    elif exists(HELPER_PATH) and "firewall" not in helper_features():
        problems.append(OLD_HELPER)
    return problems
