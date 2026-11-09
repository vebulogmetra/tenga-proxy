"""Отпечаток сети на Windows: маршрут по умолчанию мимо туннелей из снимка сети."""

from __future__ import annotations

from src.sys.windows import netinfo


def default_route() -> tuple[str, str] | None:
    """(шлюз, интерфейс) физического маршрута по умолчанию или None, если его нет."""
    # Сеть только что сменилась: снимок из кэша мог её не застать.
    netinfo.invalidate()
    route = netinfo.default_route(netinfo.snapshot())
    return None if route is None else (route.nexthop, route.alias)
