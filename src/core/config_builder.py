"""Building xray-core configurations for a profile.

Extracted from the GTK application so the logic can be reused by the new UI and
tested without a display. Behaviour is unchanged: the functions take the
AppContext explicitly instead of reading it from `self`.
"""

from __future__ import annotations

import ipaddress
import logging
import random
import socket

from src.core.context import AppContext
from src.core.dns_config import DNS_TAG, build_dns
from src.core.geo import (
    RU_DIRECT_GEOIP,
    RU_DIRECT_GEOSITES,
    GeoCatalog,
    asset_dirs,
    load_catalog,
)
from src.core.proxy_mode import TUN_INBOUND_TAG, build_inbounds_for_mode, normalize_proxy_mode
from src.core.transport_tweaks import apply_transport_tweaks
from src.db.config import (
    DEFAULT_ROUTING_ORDER,
    LOCAL_NETWORKS,
    ProxyMode,
    RoutingMode,
    RoutingSettings,
    VpnSettings,
)
from src.db.profiles import ProfileEntry
from src.sys.resolver import system_dns_servers
from src.sys.vpn import (
    get_default_interface,
    get_vpn_dns_servers,
    get_vpn_interface,
    is_vpn_active,
)

logger = logging.getLogger("tenga.core.config_builder")

BLOCK_TAG = "block"
DNS_OUT_TAG = "dns-out"


def _parse_list(
    routing: RoutingSettings, entries: list[str], catalog: GeoCatalog, list_name: str
) -> tuple[list[str], list[str]]:
    """Разобрать список на доменные и сетевые правила, отсеяв неизвестные geo-категории.

    Категория, которой нет в geosite.dat / geoip.dat, роняет ядро вместе со всем
    конфигом. Из списка запись не удаляется: появится база с этой категорией —
    правило заработает.
    """
    domains, ips = routing.parse_entries(entries)
    domains, dropped_domains = catalog.split(domains)
    ips, dropped_ips = catalog.split(ips)
    dropped = dropped_domains + dropped_ips
    if dropped:
        logger.warning(
            "Список «%s»: категорий нет в геобазах, записи пропущены: %s",
            list_name,
            ", ".join(dropped),
        )
    return domains, ips


def _physical_interface(
    *,
    tun_mode: bool,
    tun_name: str,
    vpn_interface: str | None,
    vpn_settings: VpnSettings | None,
) -> str | None:
    """Интерфейс, через который ядро выходит в сеть мимо туннелей.

    None — привязка не нужна (системный прокси без VPN) или интерфейс не найден.
    """
    if vpn_interface:
        explicit = getattr(vpn_settings, "direct_interface", "") or ""
        return explicit or get_default_interface(vpn_interface, exclude=(tun_name,))
    if tun_mode:
        return get_default_interface(exclude=(tun_name,))
    return None


def _is_loopback(host: str) -> bool:
    """Сервер на этой же машине (локальный обфускатор): через сетевой интерфейс не достать."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _bind_to_interface(outbound: dict, interface: str) -> None:
    sockopt = outbound.setdefault("streamSettings", {}).setdefault("sockopt", {})
    sockopt["interface"] = interface


def build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
    """Create xray-core configuration for profile."""
    try:
        result = profile.bean.build_core_obj_xray()

        if result.get("error"):
            logger.error(
                "Error creating profile configuration %s: %s",
                profile.id,
                result["error"],
            )
            return None

        outbound = result["outbound"]
        if "tag" not in outbound:
            outbound["tag"] = "proxy"
        apply_transport_tweaks(outbound, context.config)

        proxy_tag = outbound["tag"]
        port = context.config.inbound_socks_port

        routing = profile.routing_settings
        if routing is None:
            routing = context.config.routing
            if routing.mode == RoutingMode.CUSTOM:
                routing.load_lists_from_files(context.config_dir)

        route_rules: list[dict] = []
        try:
            rule_order = routing.get_rule_order()
        except AttributeError:
            rule_order = DEFAULT_ROUTING_ORDER
        vpn_settings = profile.vpn_settings
        vpn_tag = None
        vpn_interface = None
        direct_domains: list[str] = []
        direct_ips: list[str] = []
        vpn_domains: list[str] = []
        vpn_ips: list[str] = []
        proxy_domains: list[str] = []
        proxy_ips: list[str] = []
        block_domains: list[str] = []

        # Process VPN routing rules (only if VPN is enabled and active)
        if vpn_settings and vpn_settings.enabled:
            if is_vpn_active(vpn_settings.connection_name):
                if vpn_settings.interface_name:
                    vpn_interface = vpn_settings.interface_name
                else:
                    vpn_interface = get_vpn_interface(vpn_settings.connection_name)

                if vpn_interface:
                    vpn_tag = "vpn"
                    logger.info("VPN integration enabled, interface: %s", vpn_interface)
                else:
                    logger.warning("VPN is enabled but interface not found")
            else:
                logger.warning(
                    "VPN integration enabled but connection '%s' is not active",
                    vpn_settings.connection_name,
                )

        if routing.mode == RoutingMode.CUSTOM:
            catalog = load_catalog(asset_dirs(context.find_xray_binary()))

            if routing.direct_list:
                direct_domains, direct_ips = _parse_list(
                    routing, routing.direct_list, catalog, "direct"
                )

            if routing.vpn_list and vpn_tag and vpn_interface:
                vpn_domains, vpn_ips = _parse_list(routing, routing.vpn_list, catalog, "vpn")

            if routing.proxy_list:
                proxy_domains, proxy_ips = _parse_list(
                    routing, routing.proxy_list, catalog, "proxy"
                )

            # Блок-лист — раньше пользовательских групп при любом их порядке.
            block_domains, block_ips = _parse_list(routing, routing.block_list, catalog, "block")
            if block_domains:
                route_rules.append(
                    {"type": "field", "domain": block_domains, "outboundTag": BLOCK_TAG}
                )
            if block_ips:
                route_rules.append({"type": "field", "ip": block_ips, "outboundTag": BLOCK_TAG})

            for group in rule_order:
                if group == "direct":
                    if direct_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": direct_ips,
                                "outboundTag": "direct",
                            }
                        )
                        logger.debug(
                            "Added DIRECT routing from list for IPs (order %s): %s",
                            rule_order,
                            direct_ips,
                        )
                    if direct_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": direct_domains,
                                "outboundTag": "direct",
                            }
                        )
                        logger.debug(
                            "Added DIRECT routing from list for domains (order %s): %s",
                            rule_order,
                            direct_domains,
                        )
                elif group == "vpn" and vpn_tag and vpn_interface:
                    if vpn_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": vpn_ips,
                                "outboundTag": vpn_tag,
                            }
                        )
                        logger.debug(
                            "Added VPN routing from list for IPs (order %s): %s",
                            rule_order,
                            vpn_ips,
                        )
                    if vpn_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": vpn_domains,
                                "outboundTag": vpn_tag,
                            }
                        )
                        logger.debug(
                            "Added VPN routing from list for domains (order %s): %s",
                            rule_order,
                            vpn_domains,
                        )
                elif group == "proxy":
                    if proxy_ips:
                        route_rules.append(
                            {
                                "type": "field",
                                "ip": proxy_ips,
                                "outboundTag": proxy_tag,
                            }
                        )
                        logger.debug(
                            "Added PROXY routing from list for IPs (order %s): %s",
                            rule_order,
                            proxy_ips,
                        )
                    if proxy_domains:
                        route_rules.append(
                            {
                                "type": "field",
                                "domain": proxy_domains,
                                "outboundTag": proxy_tag,
                            }
                        )
                        logger.debug(
                            "Added PROXY routing from list for domains (order %s): %s",
                            rule_order,
                            proxy_domains,
                        )

        # Готовые правила — после пользовательских групп: явная запись списка
        # главнее. Подсеть из списка «через VPN» не должна уйти напрямую только
        # потому, что входит в 10.0.0.0/8.
        ru_direct_domains: list[str] = []
        if routing.bypass_local_networks:
            route_rules.append(
                {"type": "field", "ip": list(LOCAL_NETWORKS), "outboundTag": "direct"}
            )
        if routing.mode == RoutingMode.CUSTOM and routing.ru_direct:
            ru_direct_domains, ru_direct_ips = _parse_list(
                routing, [*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP], catalog, "готовые правила"
            )
            if ru_direct_ips:
                route_rules.append({"type": "field", "ip": ru_direct_ips, "outboundTag": "direct"})
            if ru_direct_domains:
                route_rules.append(
                    {"type": "field", "domain": ru_direct_domains, "outboundTag": "direct"}
                )

        # Outbounds
        runtime_mode = normalize_proxy_mode(getattr(context.config, "proxy_mode", None))
        tun_name = getattr(context.config, "tun_name", "xray0")
        direct_outbound = {"protocol": "freedom", "tag": "direct"}
        physical_interface = _physical_interface(
            tun_mode=runtime_mode == ProxyMode.TUN,
            tun_name=tun_name,
            vpn_interface=vpn_interface if vpn_tag else None,
            vpn_settings=vpn_settings,
        )
        if physical_interface:
            # И прямой выход, и соединение с сервером профиля должны уходить через
            # физический интерфейс: маршрут по умолчанию ведёт в туннель (TUN
            # приложения или VPN), и без привязки они вернулись бы в него же.
            _bind_to_interface(direct_outbound, physical_interface)
            if not _is_loopback(profile.bean.server_address):
                _bind_to_interface(outbound, physical_interface)
            logger.info("Direct and proxy outbounds bound to interface: %s", physical_interface)

        outbounds = [
            outbound,
            direct_outbound,
        ]

        # Перехват DNS приложений в режиме TUN. Нужны и физический интерфейс, и
        # адреса настоящих DNS-серверов сети: `localhost` при перехвате дал бы
        # петлю, а непривязанный прямой запрос мог бы вернуться в TUN.
        system_resolvers: list[str] = []
        if runtime_mode == ProxyMode.TUN and context.config.dns.intercept and physical_interface:
            system_resolvers = system_dns_servers(physical_interface)
            if not system_resolvers:
                logger.warning("DNS-серверы сети не определены: DNS приложений не перехватывается")
        if system_resolvers:
            route_rules[:0] = [
                {
                    "type": "field",
                    "inboundTag": [TUN_INBOUND_TAG],
                    "port": "53",
                    "outboundTag": DNS_OUT_TAG,
                },
                {
                    "type": "field",
                    "inboundTag": [DNS_TAG],
                    "ip": system_resolvers,
                    "port": "53",
                    "outboundTag": "direct",
                },
            ]
            dns_outbound = {
                "protocol": "dns",
                "tag": DNS_OUT_TAG,
                "settings": {
                    # A и AAAA отвечает DNS-модуль; остальные типы запросов он не
                    # умеет — пересылаем их серверу сети, как было до перехвата.
                    "rewriteAddress": system_resolvers[0],
                    "rewritePort": 53,
                    "rules": [{"action": "hijack", "qType": "1,28"}, {"action": "direct"}],
                },
            }
            _bind_to_interface(dns_outbound, physical_interface)
            outbounds.append(dns_outbound)

        if vpn_tag and vpn_interface:
            vpn_outbound = {
                "protocol": "freedom",
                "tag": vpn_tag,
                "settings": {
                    "domainStrategy": "UseIPv4",
                },
                "streamSettings": {
                    "sockopt": {
                        "interface": vpn_interface,
                    },
                },
            }

            logger.info(
                "Added VPN outbound with interface: %s",
                vpn_interface,
            )
            outbounds.append(vpn_outbound)

        if any(rule["outboundTag"] == BLOCK_TAG for rule in route_rules):
            outbounds.append({"protocol": "blackhole", "tag": BLOCK_TAG})

        if vpn_settings:
            if vpn_settings.enabled:
                if vpn_tag:
                    logger.info(
                        "Profile configuration: VPN enabled and active, proxy + VPN routing"
                    )
                else:
                    logger.info("Profile configuration: VPN enabled but not active, proxy only")
            else:
                logger.info("Profile configuration: VPN disabled, proxy + direct rules (if any)")
        else:
            logger.info("Profile configuration: No VPN settings, proxy only")
        vpn_active = bool(vpn_tag and vpn_interface)
        vpn_dns_servers: list[str] = []
        if vpn_active and vpn_domains:
            vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)
        # Серверы DNS идут в том же порядке, что и группы правил: имя должен
        # резолвить DNS той сети, в которую уйдёт сам трафик.
        domains_by_group = {"direct": direct_domains, "vpn": vpn_domains, "proxy": proxy_domains}
        dns = build_dns(
            context.config.dns,
            proxy_host=profile.bean.server_address if profile.bean else "",
            domain_groups=[
                *((group, domains_by_group[group]) for group in rule_order),
                ("direct", ru_direct_domains),
            ],
            blocked_domains=block_domains,
            vpn_active=vpn_active,
            vpn_dns_servers=vpn_dns_servers,
            system_resolvers=system_resolvers,
        )

        inbounds = build_inbounds_for_mode(
            mode=getattr(context.config, "proxy_mode", None),
            address=context.config.inbound_address,
            socks_port=port,
            tun_name=getattr(context.config, "tun_name", "xray0"),
            tun_mtu=getattr(context.config, "tun_mtu", 1500),
        )

        config = {
            "log": {"loglevel": context.config.log_level},
            "dns": dns,
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {
                "domainStrategy": "IPOnDemand",
                "rules": route_rules,
            },
        }

        # Note: xray-core automatically uses the first outbound as default
        # if no routing rules match. No need to add a catch-all rule.

        return config

    except Exception as e:
        logger.exception(
            "Error creating profile configuration %s: %s",
            getattr(profile, "id", "?"),
            e,
        )
        return None


def reserve_latency_port_pair(host: str) -> int:
    """
    Reserve a free consecutive TCP port pair (socks, http=socks+1).

    Args:
        host: Listen host for xray inbounds

    Returns:
        Base SOCKS port
    """
    start_port = random.randint(20000, 50000)

    for offset in range(15000):
        port = start_port + offset
        if port >= 65000:
            break

        sock_one = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock_two = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock_one.bind((host, port))
            sock_two.bind((host, port + 1))
            return port
        except OSError:
            continue
        finally:
            sock_one.close()
            sock_two.close()

    raise RuntimeError("No free consecutive port pair found for latency test")


def build_latency_probe_config(
    context: AppContext, profile: ProfileEntry | None
) -> tuple[dict, int] | None:
    """
    Create temporary xray config for latency test.

    Uses profile outbound/routing/dns from normal config but forces
    SYSTEM_PROXY inbounds to avoid TUN conflicts with active session.
    """
    config = build_session_config(context, profile)
    if not config:
        return None

    listen_host = context.config.inbound_address
    socks_port = reserve_latency_port_pair(listen_host)
    inbounds = build_inbounds_for_mode(
        mode=ProxyMode.SYSTEM_PROXY,
        address=listen_host,
        socks_port=socks_port,
        tun_name=getattr(context.config, "tun_name", "xray0"),
        tun_mtu=getattr(context.config, "tun_mtu", 1500),
    )
    config["inbounds"] = inbounds
    return config, socks_port
