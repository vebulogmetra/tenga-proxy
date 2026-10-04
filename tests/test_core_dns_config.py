"""Блок `dns` конфига сессии."""

from __future__ import annotations

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, VpnSettings
from tests.support.session import (
    make_context,
    make_profile,
    use_bundled_geo,
    use_custom_lists,
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


# Сервер профиля задан доменом: его имя всегда резолвит системный резолвер,
# иначе DNS через прокси ждал бы соединения с прокси, а оно — DNS.
BOOTSTRAP = {"address": "localhost", "domains": ["proxy.example.org"]}


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, [{"address": "https://dns.google/dns-query"}, BOOTSTRAP]),
        ({"use_proxy": False}, [{"address": "https+local://dns.google/dns-query"}, BOOTSTRAP]),
        ({"provider": DnsProvider.SYSTEM}, ["localhost", BOOTSTRAP]),
        ({"custom_url": "8.8.8.8"}, [{"address": "8.8.8.8", "port": 53}, BOOTSTRAP]),
        ({"custom_url": "tls://dns.google"}, [BOOTSTRAP]),
    ],
    ids=["doh", "doh-direct", "system", "udp", "dot-skipped"],
)
def test_main_server_follows_dns_settings(context, profile, settings, expected):
    for name, value in settings.items():
        setattr(context.config.dns, name, value)

    assert dns_of(context, profile) == {"servers": expected}


def test_ip_server_needs_no_bootstrap_rule(context):
    profile = make_profile(context, IP_SERVER_LINK)

    assert dns_of(context, profile) == {
        "servers": [{"address": "https://dns.google/dns-query"}, "localhost"]
    }


def test_active_vpn_replaces_doh_with_system_resolver(context, profile, vpn):
    """DoH поверх VPN даёт кольцевую зависимость: резолвит системный резолвер."""
    assert dns_of(context, profile) == {"servers": ["localhost", BOOTSTRAP]}


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
        "localhost",
        BOOTSTRAP,
        {"address": address, "port": port, "domains": ["domain:corp.example"]},
    ]


def test_vpn_without_dns_servers_resolves_its_domains_locally(context, profile, vpn, monkeypatch):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [
        "localhost",
        BOOTSTRAP,
        {"address": "localhost", "domains": ["domain:corp.example"]},
    ]


def test_unreadable_vpn_dns_address_falls_back_to_public_resolver(
    context, profile, vpn, monkeypatch
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["not-an-address"])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"][-1] == {
        "address": "8.8.8.8",
        "port": 53,
        "domains": ["domain:corp.example"],
    }
