"""Чего не хватает для режима TUN на Windows: TUN поднимает служба."""

from __future__ import annotations

from collections.abc import Callable

NO_SERVICE = "Служба Tenga Proxy не установлена: TUN-режим недоступен. Переустановите приложение"


def _query(name: str) -> None:
    import win32serviceutil

    win32serviceutil.QueryServiceStatus(name)


def tun_problems(xray_path: str | None, *, query: Callable[[str], None] = _query) -> list[str]:
    """Только наличие службы: остальное она проверяет сама и сообщает при старте.

    Состояние службы запрашивается у SCM, без запуска и без pipe: проверка
    идёт при открытии настроек и не должна ждать.
    """
    from src.winsvc.service import SERVICE_NAME

    try:
        query(SERVICE_NAME)
    except Exception:
        return [NO_SERVICE]
    return []
