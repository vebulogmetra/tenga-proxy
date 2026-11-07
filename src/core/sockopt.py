"""Опции сокетов outbound'ов: привязка к интерфейсу, метка, разрешение имени в ядре.

Общие для рабочего конфига (`config_builder`) и пробного ядра (`batch_probe`): оба
должны выходить в сеть мимо туннеля одинаково.
"""

from __future__ import annotations

import ipaddress


def _sockopt(outbound: dict) -> dict:
    return outbound.setdefault("streamSettings", {}).setdefault("sockopt", {})


def bind_to_interface(outbound: dict, interface: str) -> None:
    """SO_BINDTODEVICE на Linux, IP_UNICAST_IF на Windows: маршрут ищется только на интерфейсе."""
    _sockopt(outbound)["interface"] = interface


def mark_socket(outbound: dict, mark: int) -> None:
    """Метка пропускает трафик ядра мимо таблицы `inet veblock` (см. tun_route_helper.sh)."""
    _sockopt(outbound)["mark"] = mark


def resolve_in_core(outbound: dict) -> None:
    """Имя сервера разрешает DNS-модуль ядра, а не системный резолвер.

    Системный резолвер шлёт запрос без метки и привязки, то есть в туннель. На SNI это
    не влияет: `serverName` не меняется.
    """
    _sockopt(outbound)["domainStrategy"] = "UseIPv4"


def is_loopback(host: str) -> bool:
    """Сервер на этой же машине (локальный обфускатор): через сетевой интерфейс не достать."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True
