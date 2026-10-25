"""Следы прежней установки AppImage в домашнем каталоге.

`install_appimage.sh` клал ярлык в `~/.local/share/applications` под тем же
именем, что и deb-пакет. Ярлык пользователя перекрывает системный, и меню
запускало бы старую AppImage вместо пакета. Удаляются только ярлык и его
значки; сам файл AppImage и конфигурацию пользователь удалит сам.
"""

from __future__ import annotations

import os
from pathlib import Path

DESKTOP_ID = "tenga-proxy.desktop"
ICON_SIZES = (64, 128, 256)


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _points_to_appimage(desktop: Path) -> bool:
    try:
        text = desktop.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(
        line.startswith("Exec=") and ".appimage" in line.lower() for line in text.splitlines()
    )


def remove_appimage_launcher(home: Path) -> list[Path]:
    """Удалить ярлык AppImage и его значки; вернуть удалённые файлы."""
    desktop = home / "applications" / DESKTOP_ID
    if not _points_to_appimage(desktop):
        return []
    icons = [
        home / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "tenga-proxy.png"
        for size in ICON_SIZES
    ]
    removed = []
    for path in (desktop, *icons):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    return removed
