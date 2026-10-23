"""Общие проверки адресов для Linux- и Windows-реализаций."""

from __future__ import annotations

import ipaddress


def usable_ipv4(value: str) -> str | None:
    """IPv4-адрес настоящего сервера; loopback — заглушка локального резолвера."""
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback:
        return None
    return str(address)
