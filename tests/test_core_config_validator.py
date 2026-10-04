"""Проверка готового конфига перед запуском ядра.

Каждое правило ловит ошибку, которую ядро приняло бы молча, а пользователь
получил бы утечку мимо прокси или петлю.
"""

from __future__ import annotations

import copy

import pytest

from src.core import config_builder
from src.core.config_builder import UnsafeConfigError, build_session_config
from src.core.config_validator import exposed_inbounds, validate_session_config
from src.db.config import ProxyMode, VpnSettings
from tests.support.session import make_context, make_profile, use_bundled_geo, use_custom_lists


def valid_config() -> dict:
    return {
        "dns": {"servers": [{"address": "https://dns.google/dns-query"}]},
        "inbounds": [{"listen": "127.0.0.1", "port": 2080, "protocol": "socks"}],
        "outbounds": [
            {"protocol": "vless", "tag": "proxy"},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "rules": [{"type": "field", "domain": ["domain:a.example"], "outboundTag": "direct"}]
        },
    }


def tun_config() -> dict:
    config = valid_config()
    config["inbounds"] = [{"tag": "tun-in", "port": 0, "protocol": "tun"}]
    config["dns"] = {"tag": "dns-internal", "servers": [{"address": "192.168.0.1", "port": 53}]}
    config["outbounds"].append({"protocol": "dns", "tag": "dns-out"})
    config["routing"]["rules"] = [
        {"type": "field", "inboundTag": ["tun-in"], "port": "53", "outboundTag": "dns-out"},
        {
            "type": "field",
            "inboundTag": ["dns-internal"],
            "ip": ["192.168.0.1"],
            "port": "53",
            "outboundTag": "direct",
        },
    ]
    return config


def test_valid_configs_pass():
    assert validate_session_config(valid_config()) == []
    assert validate_session_config(tun_config()) == []


def test_config_without_outbounds_is_rejected():
    config = valid_config()
    config["outbounds"] = []

    assert validate_session_config(config) == ["в конфиге нет ни одного outbound"]


@pytest.mark.parametrize("protocol", ["freedom", "blackhole", "dns"])
def test_default_outbound_must_be_the_proxy(protocol):
    """Первый outbound — выход по умолчанию: всё несопоставленное ушло бы мимо прокси."""
    config = valid_config()
    config["outbounds"].insert(0, {"protocol": protocol, "tag": "first"})

    (violation,) = validate_session_config(config)

    assert "первый outbound" in violation
    assert protocol in violation


@pytest.mark.parametrize("target", ["direct", "block"])
def test_rule_without_conditions_must_not_bypass_the_proxy(target):
    config = valid_config()
    config["outbounds"].append({"protocol": "blackhole", "tag": "block"})
    config["routing"]["rules"].append(
        {"type": "field", "network": "tcp,udp", "outboundTag": target}
    )

    (violation,) = validate_session_config(config)

    assert "без условий" in violation


def test_rule_without_conditions_may_lead_to_the_proxy():
    config = valid_config()
    config["routing"]["rules"].append(
        {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}
    )

    assert validate_session_config(config) == []


@pytest.mark.parametrize("network", ["127.0.0.0/8", "::1/128", "geoip:private"])
def test_loopback_must_not_be_sent_to_the_proxy(network):
    config = valid_config()
    config["routing"]["rules"].append({"type": "field", "ip": [network], "outboundTag": "proxy"})

    (violation,) = validate_session_config(config)

    assert network in violation


def test_rule_must_point_to_an_existing_outbound():
    """Опечатку в теге ядро молча заменяет выходом по умолчанию."""
    config = valid_config()
    config["routing"]["rules"].append({"type": "field", "ip": ["1.1.1.1"], "outboundTag": "vpn"})

    (violation,) = validate_session_config(config)

    assert "vpn" in violation


def test_dns_interception_rule_must_be_first():
    """Иначе адрес DNS-сервера совпадёт с IP-правилом раньше и запрос уйдёт мимо DNS-модуля."""
    config = tun_config()
    config["routing"]["rules"].insert(
        0, {"type": "field", "ip": ["8.8.8.8"], "outboundTag": "direct"}
    )

    (violation,) = validate_session_config(config)

    assert "первым" in violation


def test_intercepting_config_must_not_use_localhost_dns():
    """Запрос ядра к системному резолверу вернулся бы в TUN и был бы перехвачен снова."""
    config = tun_config()
    config["dns"]["servers"].append("localhost")

    (violation,) = validate_session_config(config)

    assert "localhost" in violation


def test_intercepting_config_must_route_own_dns_queries_directly():
    config = tun_config()
    del config["routing"]["rules"][1]

    (violation,) = validate_session_config(config)

    assert "dns-internal" in violation


def test_non_loopback_inbound_is_reported_but_allowed():
    """Адрес входящего соединения задаёт пользователь: это предупреждение, не отказ."""
    config = valid_config()
    config["inbounds"].append({"listen": "0.0.0.0", "port": 2081, "protocol": "http"})

    assert validate_session_config(config) == []
    assert exposed_inbounds(config) == ["http 0.0.0.0:2081"]
    assert exposed_inbounds(valid_config()) == []


# --- сборщик и проверка вместе --------------------------------------------


@pytest.fixture
def context(tmp_path, monkeypatch):
    use_bundled_geo(monkeypatch)
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.mark.parametrize("mode", ProxyMode.ALL)
def test_builder_output_passes_validation(context, profile, monkeypatch, mode):
    """Всё, что сборщик умеет, собрано разом: списки, готовые правила, VPN, перехват DNS."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    context.config.proxy_mode = mode
    context.config.routing.ru_direct = True
    use_custom_lists(
        context,
        direct=["direct.example", "192.168.5.0/24"],
        proxy=["blocked.example"],
        vpn=["corp.example", "10.14.0.0/16"],
        block=["ads.example"],
    )

    config = build_session_config(context, profile)

    assert validate_session_config(copy.deepcopy(config)) == []


def test_private_geoip_in_proxy_list_is_dropped_by_the_builder(context, profile):
    """`geoip:private` в прокси увёл бы туда и loopback — запись пропускаем."""
    use_custom_lists(context, proxy=["geoip:private", "blocked.example"], direct=["geoip:private"])

    config = build_session_config(context, profile)

    proxy_rules = [r for r in config["routing"]["rules"] if r["outboundTag"] != "direct"]
    assert "geoip:private" not in str(proxy_rules)
    assert "geoip:private" in str(config["routing"]["rules"])


def test_unsafe_config_is_refused_with_the_reason(context, profile):
    use_custom_lists(context, proxy=["127.0.0.0/8"])

    with pytest.raises(UnsafeConfigError, match=r"127\.0\.0\.0/8"):
        build_session_config(context, profile)
