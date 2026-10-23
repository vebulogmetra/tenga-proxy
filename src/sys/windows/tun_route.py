"""Маршруты TUN на Windows. Их ставит служба Tenga Proxy (фаза 3 порта)."""

from __future__ import annotations

from dataclasses import dataclass

NO_SERVICE = "TUN-режим на Windows требует службу Tenga Proxy; она ещё не установлена"


@dataclass
class TunRouteState:
    tun_name: str
    proxy_ip: str


def apply_tun_routes(tun_name: str, proxy_host: str) -> tuple[bool, TunRouteState | None, str]:
    return False, None, NO_SERVICE


def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    if state is None:
        return True, ""
    return False, NO_SERVICE
