"""Блок `dns` конфига xray-core.

Сервер описывается сразу в формате ядра: строка `"localhost"` либо объект
`{"address", "port"?, "domains"?}`. Ядро сначала спрашивает серверы, у которых
`domains` совпал с именем, затем остальные по порядку.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.db.config import DnsSettings

logger = logging.getLogger("tenga.core.dns_config")

# Системный резолвер процесса ядра.
LOCALHOST = "localhost"
# Запасной адрес, когда DNS-сервер VPN не удалось разобрать.
FALLBACK_VPN_DNS = ("8.8.8.8", 53)

_IPV4_ENDPOINT = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?")

DnsServer = str | dict[str, Any]


def parse_dns_endpoint(raw: str) -> tuple[str, int] | None:
    """IPv4-адрес и порт DNS-сервера из строки NetworkManager.

    nmcli отдаёт и `10.222.0.7`, и `IP4.DNS[1]:10.222.0.7:5353` — берём первый
    IPv4-адрес в строке и порт сразу за ним.
    """
    match = _IPV4_ENDPOINT.search(raw)
    if not match:
        return None
    return match.group(1), int(match.group(2) or 53)


def _server(
    address: str, *, port: int | None = None, domains: list[str] | None = None
) -> DnsServer:
    if address == LOCALHOST and not domains:
        return LOCALHOST
    server: dict[str, Any] = {"address": address}
    if port is not None:
        server["port"] = port
    if domains:
        server["domains"] = list(domains)
    return server


def _main_server(dns_url: str, *, through_proxy: bool) -> DnsServer | None:
    """Сервер для всех имён, у которых нет своего сервера."""
    if dns_url == "local":
        return LOCALHOST
    if dns_url.startswith("https://"):
        # DoH: ядро принимает его только URL-строкой в address. Отдельные
        # host:port и path оно читает как имя UDP-сервера — запрос висит до
        # таймаута и уходит на localhost. `https+local://` идёт напрямую, мимо
        # маршрутизации; обычный `https://` — через неё, то есть в прокси.
        if not through_proxy:
            dns_url = "https+local://" + dns_url[len("https://") :]
        return _server(dns_url)
    if dns_url.startswith("tls://"):
        # DoT в xray-core нет: адрес `tls://…` оно прочло бы как имя UDP-сервера.
        logger.warning("DNS-over-TLS не поддерживается xray-core, %s пропущен", dns_url)
        return None
    return _server(dns_url.replace("udp://", "").replace("tcp://", ""), port=53)


def _vpn_server(vpn_dns_servers: list[str], vpn_domains: list[str]) -> DnsServer:
    """Сервер для доменов из списка «через VPN»."""
    if not vpn_dns_servers:
        logger.warning("У VPN-подключения нет DNS-серверов: его домены резолвит системный")
        return _server(LOCALHOST, domains=vpn_domains)

    endpoint = parse_dns_endpoint(vpn_dns_servers[0])
    if endpoint is None:
        logger.error("Не удалось разобрать адрес DNS-сервера VPN: %s", vpn_dns_servers[0])
        endpoint = FALLBACK_VPN_DNS
    address, port = endpoint
    logger.info("Домены списка «через VPN» резолвит %s:%d", address, port)
    return _server(address, port=port, domains=vpn_domains)


def build_dns(
    settings: DnsSettings,
    *,
    proxy_host: str,
    vpn_active: bool = False,
    vpn_domains: list[str] | None = None,
    vpn_dns_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Собрать блок `dns`.

    Args:
        settings: настройки DNS приложения.
        proxy_host: адрес сервера профиля; домен резолвится системным резолвером.
        vpn_active: поднят VPN NetworkManager, привязанный к профилю.
        vpn_domains: доменные правила списка «через VPN».
        vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
    """
    dns_url = settings.get_dns_url()
    if vpn_active and dns_url.startswith(("https://", "tls://")):
        # DoH поверх VPN даёт кольцевую зависимость, а приватность DNS уже
        # обеспечивает сам VPN.
        logger.info("VPN активен: DoH/DoT заменён системным резолвером")
        dns_url = "local"

    servers: list[DnsServer] = []

    main = _main_server(dns_url, through_proxy=settings.use_proxy)
    if main is not None:
        servers.append(main)

    # Имя сервера профиля резолвит системный резолвер: DNS через прокси ждал бы
    # соединения с прокси, а оно — этого самого ответа.
    bootstrap = [proxy_host] if proxy_host and not proxy_host[0].isdigit() else []
    servers.append(_server(LOCALHOST, domains=bootstrap))

    if vpn_active and vpn_domains:
        servers.append(_vpn_server(vpn_dns_servers or [], vpn_domains))

    return {"servers": servers}
