"""Общие проверки адресов для Linux- и Windows-реализаций."""

from __future__ import annotations

import ipaddress
import logging
import socket

logger = logging.getLogger("tenga.sys.addresses")


def usable_ipv4(value: str) -> str | None:
    """IPv4-адрес настоящего сервера; loopback — заглушка локального резолвера."""
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback:
        return None
    return str(address)


def resolve_ipv4(host: str) -> str | None:
    """Resolve host to IPv4 address."""
    host = (host or "").strip()
    if not host:
        return None

    try:
        return str(ipaddress.IPv4Address(host))
    except Exception:
        pass

    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        for info in infos:
            ip = info[4][0]
            if ip:
                try:
                    return str(ipaddress.IPv4Address(ip))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Failed to resolve host '%s': %s", host, e)
    return None
