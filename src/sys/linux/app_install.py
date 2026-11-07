"""На Linux приложение ставится пакетом: самообновления нет."""

from __future__ import annotations

from pathlib import Path


def can_self_update() -> bool:
    return False


def launch_installer(path: Path) -> None:
    raise NotImplementedError("Самообновление доступно только на Windows")
