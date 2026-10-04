"""Перехват DNS-запросов приложений в режиме TUN.

Без него настройки DNS действуют только на внутренний резолв ядра, а запросы
приложений идут мимо: split-DNS и блок-лист на них не влияют.
"""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, ProxyMode, VpnSettings
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

DOH = "https://dns.google/dns-query"
INTERCEPT_RULE = {
    "type": "field",
    "inboundTag": ["tun-in"],
    "port": "53",
    "outboundTag": "dns-out",
}


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    context = make_context(tmp_path)
    context.config.proxy_mode = ProxyMode.TUN
    return context


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def system(monkeypatch):
    """Система с интерфейсом eth0 и резолвером 192.168.0.1 на нём."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])


def outbound_tags(config: dict) -> set[str]:
    return {o.get("tag") for o in config["outbounds"]}


def test_dns_queries_from_tun_are_handed_to_the_dns_module(context, profile, system):
    config = build_session_config(context, profile)

    # Первым: иначе адрес DNS-сервера совпал бы с каким-нибудь IP-правилом раньше.
    assert config["routing"]["rules"][0] == INTERCEPT_RULE
    assert {
        "protocol": "dns",
        "tag": "dns-out",
        "settings": {
            # A и AAAA отвечает DNS-модуль ядра; остальные типы (TXT, MX, SRV…) он
            # не умеет — их пересылаем системному резолверу, как было до перехвата.
            "rewriteAddress": "192.168.0.1",
            "rewritePort": 53,
            "rules": [{"action": "hijack", "qType": "1,28"}, {"action": "direct"}],
        },
        "streamSettings": {"sockopt": {"interface": "eth0"}},
    } in config["outbounds"]


def test_system_resolver_is_addressed_explicitly(context, profile, system):
    """`localhost` при перехвате дал бы петлю: запрос ядра вернулся бы в TUN.

    Поэтому системный резолвер пишется адресом, а его запросы отдельным
    правилом уходят в direct, привязанный к физическому интерфейсу.
    """
    use_custom_lists(context, direct=["direct.example"])

    config = build_session_config(context, profile)

    assert config["dns"]["tag"] == "dns-internal"
    assert config["dns"]["servers"] == [
        {
            "address": "192.168.0.1",
            "port": 53,
            "domains": ["full:proxy.example.org"],
            "skipFallback": True,
        },
        {
            "address": "192.168.0.1",
            "port": 53,
            "domains": ["domain:direct.example"],
            "skipFallback": True,
        },
        {"address": DOH},
    ]
    assert config["routing"]["rules"][1] == {
        "type": "field",
        "inboundTag": ["dns-internal"],
        "ip": ["192.168.0.1"],
        "port": "53",
        "outboundTag": "direct",
    }


def test_system_dns_provider_uses_the_explicit_resolver_too(context, profile, system):
    context.config.dns.provider = DnsProvider.SYSTEM

    servers = build_session_config(context, profile)["dns"]["servers"]

    assert "localhost" not in str(servers)
    assert servers[-1] == {"address": "192.168.0.1", "port": 53}


def test_block_list_comes_right_after_the_dns_rules(context, profile, system):
    use_custom_lists(context, block=["ads.example"])

    rules = build_session_config(context, profile)["routing"]["rules"]

    assert [r["outboundTag"] for r in rules[:3]] == ["dns-out", "direct", "block"]


def test_no_interception_in_system_proxy_mode(context, profile, system):
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert "tag" not in config["dns"]
    assert "localhost" in str(config["dns"]["servers"])


def test_interception_can_be_switched_off(context, profile, system):
    context.config.dns.intercept = False

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert INTERCEPT_RULE not in config["routing"]["rules"]


def test_no_interception_without_known_system_resolver(context, profile, monkeypatch):
    """Не знаем, куда слать прямые запросы, — оставляем `localhost` и не перехватываем."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: [])

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert "localhost" in str(config["dns"]["servers"])


def test_no_interception_without_physical_interface(context, profile, monkeypatch):
    """Без привязки к интерфейсу прямой запрос к резолверу мог бы вернуться в TUN."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)


def test_interception_with_active_vpn_keeps_vpn_dns(context, profile, system, monkeypatch):
    """Режим «VPN поверх»: домены VPN-списка по-прежнему резолвит DNS-сервер VPN."""
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    use_custom_lists(context, vpn=["corp.example", "10.222.0.0/16"])

    config = build_session_config(context, profile)

    assert config["routing"]["rules"][0] == INTERCEPT_RULE
    assert {
        "address": "10.222.0.7",
        "port": 53,
        "domains": ["domain:corp.example"],
        "skipFallback": True,
    } in config["dns"]["servers"]
    # DoH при активном VPN заменяется системным резолвером — здесь его адресом.
    assert config["dns"]["servers"][-1] == {"address": "192.168.0.1", "port": 53}
    assert "vpn" in outbound_tags(config)


def test_dns_outbound_traffic_is_not_counted_as_proxy_traffic():
    from src.core.xray_manager import XrayManager

    assert "dns-out" in XrayManager._SERVICE_TAGS


@needs_xray
def test_core_accepts_interception_config(context, profile, system, tmp_path):
    """Правило с `inboundTag: tun-in` проверяем на SOCKS-входе с тем же тегом."""
    use_custom_lists(
        context,
        direct=["direct.example", "geosite:category-ru"],
        proxy=["blocked.example"],
        block=["ads.example"],
    )
    context.config.routing.ru_direct = True

    config = build_session_config(context, profile)

    assert config["inbounds"][0]["protocol"] == "tun"
    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
