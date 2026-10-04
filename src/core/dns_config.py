"""Блок `dns` конфига xray-core.

Сервер описывается сразу в формате ядра: строка `"localhost"` либо объект
`{"address", "port"?, "domains"?, "skipFallback"?}`. Ядро сначала спрашивает
серверы, у которых `domains` совпал с именем, затем остальные по порядку;
сервер со `skipFallback` чужих имён не получает вовсе.

Раскладка (split-DNS):

1. имя сервера профиля — системный резолвер;
2. домены списков — по порядку групп маршрутизации: «напрямую» резолвит
   системный резолвер, «через VPN» — DNS-сервер VPN, «через прокси» —
   удалённый DNS;
3. всё остальное — основной DNS из настроек.

Системный резолвер помечен `skipFallback`: если удалённый DNS недоступен
(туннель упал), остальные имена не утекают провайдеру.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from src.db.config import DnsSettings

logger = logging.getLogger("tenga.core.dns_config")

# Системный резолвер процесса ядра.
LOCALHOST = "localhost"
# Тег, которым помечены собственные запросы DNS-модуля в маршрутизации.
DNS_TAG = "dns-internal"
# Значение `hosts`: ответить кодом 3 (NXDOMAIN). Адрес-заглушка вроде 127.0.0.1
# не годится — он попадает под «локальные сети напрямую».
NXDOMAIN = "#3"
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
    address: str,
    *,
    port: int | None = None,
    domains: list[str] | None = None,
) -> DnsServer:
    """Сервер в формате ядра; с `domains` он обслуживает только их."""
    if not domains:
        return address if port is None else {"address": address, "port": port}
    server: dict[str, Any] = {"address": address}
    if port is not None:
        server["port"] = port
    server["domains"] = list(domains)
    server["skipFallback"] = True
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
        return {"address": dns_url}
    if dns_url.startswith("tls://"):
        # DoT в xray-core нет: адрес `tls://…` оно прочло бы как имя UDP-сервера.
        logger.warning("DNS-over-TLS не поддерживается xray-core, %s пропущен", dns_url)
        return None
    return _server(dns_url.replace("udp://", "").replace("tcp://", ""), port=53)


def _system_servers(
    system_resolvers: Sequence[str], domains: list[str] | None = None
) -> list[DnsServer]:
    """Системный резолвер: `localhost` либо — при перехвате DNS — серверы сети адресами.

    При перехвате `localhost` дал бы петлю: запрос ядра к системному резолверу
    вернулся бы в TUN и был бы перехвачен снова.
    """
    if not system_resolvers:
        return [_server(LOCALHOST, domains=domains)]
    return [_server(address, port=53, domains=domains) for address in system_resolvers]


def _vpn_servers(
    vpn_dns_servers: list[str], vpn_domains: list[str], system_resolvers: Sequence[str]
) -> list[DnsServer]:
    """Серверы для доменов из списка «через VPN»."""
    if not vpn_dns_servers:
        logger.warning("У VPN-подключения нет DNS-серверов: его домены резолвит системный")
        return _system_servers(system_resolvers, vpn_domains)

    endpoint = parse_dns_endpoint(vpn_dns_servers[0])
    if endpoint is None:
        logger.error("Не удалось разобрать адрес DNS-сервера VPN: %s", vpn_dns_servers[0])
        endpoint = FALLBACK_VPN_DNS
    address, port = endpoint
    logger.info("Домены списка «через VPN» резолвит %s:%d", address, port)
    return [_server(address, port=port, domains=vpn_domains)]


def build_dns(
    settings: DnsSettings,
    *,
    proxy_host: str,
    domain_groups: Sequence[tuple[str, list[str]]] = (),
    blocked_domains: Sequence[str] = (),
    vpn_active: bool = False,
    vpn_dns_servers: list[str] | None = None,
    system_resolvers: Sequence[str] = (),
) -> dict[str, Any]:
    """Собрать блок `dns`.

    Args:
        settings: настройки DNS приложения.
        proxy_host: адрес сервера профиля; домен резолвится системным резолвером.
        domain_groups: доменные правила списков по группам (`direct`, `vpn`,
            `proxy`) в порядке групп маршрутизации.
        blocked_domains: доменные правила блок-листа — на них отвечаем NXDOMAIN.
        vpn_active: поднят VPN NetworkManager, привязанный к профилю.
        vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
        system_resolvers: адреса DNS-серверов сети. Заданы при перехвате DNS в
            режиме TUN — тогда они заменяют `localhost`, а блок получает тег
            `DNS_TAG`, по которому их запросы направляются в direct.
    """
    dns_url = settings.get_dns_url()
    if vpn_active and dns_url.startswith(("https://", "tls://")):
        # DoH поверх VPN даёт кольцевую зависимость, а приватность DNS уже
        # обеспечивает сам VPN.
        logger.info("VPN активен: DoH/DoT заменён системным резолвером")
        dns_url = "local"

    # Без удалённого сервера (системный DNS, пропущенный DoT) всё резолвит
    # системный резолвер — тогда он законный сервер по умолчанию.
    main = _main_server(dns_url, through_proxy=settings.use_proxy) or LOCALHOST
    main_is_remote = main != LOCALHOST

    servers: list[DnsServer] = []

    # Имя сервера профиля резолвит системный резолвер: DNS через прокси ждал бы
    # соединения с прокси, а оно — этого самого ответа.
    if proxy_host and not proxy_host[0].isdigit():
        servers.extend(_system_servers(system_resolvers, [f"full:{proxy_host}"]))

    for group, domains in domain_groups:
        if not domains:
            continue
        if group == "direct":
            servers.extend(_system_servers(system_resolvers, domains))
        elif group == "vpn":
            servers.extend(_vpn_servers(vpn_dns_servers or [], domains, system_resolvers))
        elif group == "proxy" and main_is_remote:
            # Иначе домен из proxy-списка мог бы совпасть с доменами direct-сервера
            # ниже и отрезолвиться в сети провайдера.
            servers.append({**_as_object(main), "domains": list(domains)})

    if main_is_remote:
        servers.append(main)
    else:
        servers.extend(_system_servers(system_resolvers))

    dns: dict[str, Any] = {"servers": servers}
    if system_resolvers:
        dns["tag"] = DNS_TAG
    if blocked_domains:
        dns["hosts"] = {_hosts_key(rule): NXDOMAIN for rule in blocked_domains}
    return dns


def _hosts_key(rule: str) -> str:
    """Доменное правило в виде ключа `hosts`.

    Голую строку правило маршрутизации считает подстрокой, а `hosts` — точным
    именем; чтобы оба блокировали одно и то же, подстроку называем явно.
    """
    return rule if ":" in rule else f"keyword:{rule}"


def _as_object(server: DnsServer) -> dict[str, Any]:
    return {"address": server} if isinstance(server, str) else dict(server)
