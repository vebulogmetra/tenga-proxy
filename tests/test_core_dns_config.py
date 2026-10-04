"""Блок `dns` конфига сессии."""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, VpnSettings
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    use_bundled_geo,
    use_custom_lists,
    with_socks_inbound,
    xray_verdict,
)

needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

IP_SERVER_LINK = "vless://11111111-1111-1111-1111-111111111111@203.0.113.7:443?security=tls#IP"


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def vpn(monkeypatch, profile):
    """Профиль с поднятым VPN NetworkManager (интерфейс tun0)."""
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    return profile.vpn_settings


def dns_of(context, profile) -> dict:
    config = build_session_config(context, profile)
    assert config is not None
    return config["dns"]


DOH = "https://dns.google/dns-query"

# Сервер профиля задан доменом: его имя всегда резолвит системный резолвер,
# иначе DNS через прокси ждал бы соединения с прокси, а оно — DNS.
BOOTSTRAP = {"address": "localhost", "domains": ["full:proxy.example.org"], "skipFallback": True}


def direct_dns(*domains: str) -> dict:
    return {"address": "localhost", "domains": list(domains), "skipFallback": True}


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, [BOOTSTRAP, {"address": DOH}]),
        ({"use_proxy": False}, [BOOTSTRAP, {"address": "https+local://dns.google/dns-query"}]),
        ({"provider": DnsProvider.SYSTEM}, [BOOTSTRAP, "localhost"]),
        ({"custom_url": "8.8.8.8"}, [BOOTSTRAP, {"address": "8.8.8.8", "port": 53}]),
        ({"custom_url": "tls://dns.google"}, [BOOTSTRAP, "localhost"]),
    ],
    ids=["doh", "doh-direct", "system", "udp", "dot-skipped"],
)
def test_main_server_follows_dns_settings(context, profile, settings, expected):
    for name, value in settings.items():
        setattr(context.config.dns, name, value)

    assert dns_of(context, profile) == {"servers": expected}


def test_ip_server_needs_no_bootstrap_rule(context):
    profile = make_profile(context, IP_SERVER_LINK)

    assert dns_of(context, profile) == {"servers": [{"address": DOH}]}


def test_system_resolver_is_not_a_fallback_for_remote_dns(context, profile):
    """Упал туннель — имена не должны утекать системному резолверу.

    `skipFallback` оставляет системному резолверу только его домены; общего
    `localhost` после удалённого сервера нет.
    """
    use_custom_lists(context, direct=["direct.example"])

    servers = dns_of(context, profile)["servers"]

    assert "localhost" not in servers
    assert all(s.get("skipFallback") for s in servers if s["address"] == "localhost")


def test_direct_list_domains_use_the_system_resolver(context, profile):
    """Трафик идёт напрямую — и имя должен резолвить DNS той же сети.

    Иначе запрос ушёл бы через прокси, и CDN вернул бы адрес чужого региона.
    """
    use_custom_lists(context, direct=["direct.example", "geosite:category-ru", "1.2.3.0/24"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:direct.example", "geosite:category-ru"),
        {"address": DOH},
    ]


def test_proxy_list_domains_use_the_remote_dns(context, profile):
    """Домен из proxy-списка не должен достаться системному резолверу.

    Сервер с доменами proxy-списка стоит по порядку групп: при порядке
    «прокси → напрямую» домен из обоих списков резолвится удалённо.
    """
    use_custom_lists(context, direct=["ru.example"], proxy=["blocked.ru.example"])
    context.config.routing.rule_order = ["proxy", "direct", "vpn"]

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        {"address": DOH, "domains": ["domain:blocked.ru.example"]},
        direct_dns("domain:ru.example"),
        {"address": DOH},
    ]


def test_dns_servers_follow_the_rule_order(context, profile):
    use_custom_lists(context, direct=["ru.example"], proxy=["blocked.ru.example"])
    context.config.routing.rule_order = ["direct", "vpn", "proxy"]

    addresses = [s["address"] for s in dns_of(context, profile)["servers"]]

    assert addresses == ["localhost", "localhost", DOH, DOH]


def test_proxy_list_needs_no_own_server_with_system_dns(context, profile):
    """Удалённого DNS нет — отдельный сервер для proxy-списка ничего бы не изменил."""
    context.config.dns.provider = DnsProvider.SYSTEM
    use_custom_lists(context, proxy=["blocked.example"])

    assert dns_of(context, profile)["servers"] == [BOOTSTRAP, "localhost"]


def test_active_vpn_replaces_doh_with_system_resolver(context, profile, vpn):
    """DoH поверх VPN даёт кольцевую зависимость: резолвит системный резолвер."""
    assert dns_of(context, profile) == {"servers": [BOOTSTRAP, "localhost"]}


@pytest.mark.parametrize(
    ("reported", "address", "port"),
    [
        ("10.222.0.7", "10.222.0.7", 53),
        ("IP4.DNS[1]:10.222.0.7:5353", "10.222.0.7", 5353),
    ],
    ids=["plain", "nmcli"],
)
def test_vpn_list_domains_use_the_vpn_dns_server(
    context, profile, vpn, monkeypatch, reported, address, port
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [reported])
    use_custom_lists(context, vpn=["corp.example", "10.14.0.0/16"], direct=["direct.example"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:direct.example"),
        {
            "address": address,
            "port": port,
            "domains": ["domain:corp.example"],
            "skipFallback": True,
        },
        "localhost",
    ]


def test_vpn_without_dns_servers_resolves_its_domains_locally(context, profile, vpn, monkeypatch):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:corp.example"),
        "localhost",
    ]


def test_unreadable_vpn_dns_address_falls_back_to_public_resolver(
    context, profile, vpn, monkeypatch
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["not-an-address"])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"][1] == {
        "address": "8.8.8.8",
        "port": 53,
        "domains": ["domain:corp.example"],
        "skipFallback": True,
    }


def test_vpn_list_is_ignored_while_the_vpn_is_down(context, profile):
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [BOOTSTRAP, {"address": DOH}]


@needs_xray
@pytest.mark.parametrize("provider", DnsProvider.ALL)
def test_core_accepts_split_dns(context, profile, tmp_path, provider):
    context.config.dns.provider = provider
    use_custom_lists(
        context,
        direct=["direct.example", "geosite:category-ru", "geoip:ru"],
        proxy=["*.blocked.example", "geosite:google"],
    )

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)


def test_ru_direct_resolves_russian_sites_with_the_system_resolver(context, profile):
    """Готовое правило стоит после пользовательских: домен из proxy-списка главнее."""
    use_custom_lists(context, proxy=["blocked.ru.example"])
    context.config.routing.ru_direct = True

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        {"address": DOH, "domains": ["domain:blocked.ru.example"]},
        direct_dns("geosite:category-ru", "geosite:category-gov-ru"),
        {"address": DOH},
    ]


VPN_DNS_RULE = {"type": "field", "ip": ["10.222.0.7"], "port": "53", "outboundTag": "vpn"}


def rules_of(context, profile) -> list[dict]:
    config = build_session_config(context, profile)
    assert config is not None
    return config["routing"]["rules"]


def test_queries_to_the_vpn_dns_server_go_through_the_vpn(context, profile, vpn):
    """Сервер VPN доступен только через VPN: без правила запрос DNS-модуля к нему
    ушёл бы в прокси, а с «локальными сетями напрямую» — мимо VPN в direct."""
    use_custom_lists(context, vpn=["corp.example"])

    rules = rules_of(context, profile)

    assert rules[0] == VPN_DNS_RULE
    assert any(
        rule["outboundTag"] == "direct" and "10.0.0.0/8" in rule.get("ip", []) for rule in rules
    )


def test_vpn_dns_rule_follows_the_interception_rules(context, profile, vpn, monkeypatch):
    """Правило перехвата обязано быть первым — правило сервера VPN идёт за ним."""
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])
    context.config.proxy_mode = "tun"
    use_custom_lists(context, vpn=["corp.example"])

    rules = rules_of(context, profile)

    assert rules[0]["outboundTag"] == "dns-out"
    assert rules[2] == VPN_DNS_RULE


@pytest.mark.parametrize("reported", [[], ["не адрес"]], ids=["no-servers", "unreadable"])
def test_no_vpn_dns_rule_without_a_known_vpn_dns_server(
    context, profile, vpn, monkeypatch, reported
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: reported)
    use_custom_lists(context, vpn=["corp.example"])

    assert not any(rule.get("port") == "53" for rule in rules_of(context, profile))


def test_no_vpn_dns_rule_without_vpn_domains(context, profile, vpn):
    """Домены VPN-списка не заданы — сервер VPN не используется, правило не нужно."""
    use_custom_lists(context, vpn=["10.14.0.0/16"])

    assert VPN_DNS_RULE not in rules_of(context, profile)


@needs_xray
def test_core_accepts_vpn_dns_rule(context, profile, vpn, tmp_path):
    use_custom_lists(context, vpn=["corp.example", "10.14.0.0/16"], direct=["direct.example"])

    config = build_session_config(context, profile)

    assert VPN_DNS_RULE in config["routing"]["rules"]
    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
