"""Привязка исходящих соединений к физическому интерфейсу в режиме TUN.

Маршрут по умолчанию в режиме TUN ведёт в сам TUN. Соединение ядра «напрямую»
без привязки к интерфейсу вернулось бы в туннель и зациклилось.
"""

from __future__ import annotations

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import ProxyMode, VpnSettings
from tests.support.session import make_context, make_profile, use_bundled_geo


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
def physical(monkeypatch):
    """Физический интерфейс системы — eth0; запоминает, что просили исключить."""
    calls: list[tuple] = []

    def fake(vpn_interface=None, exclude=()):
        calls.append((vpn_interface, tuple(exclude)))
        return "eth0"

    monkeypatch.setattr(config_builder, "get_default_interface", fake)
    return calls


def outbound(config: dict, tag: str) -> dict:
    return next(o for o in config["outbounds"] if o.get("tag") == tag)


def bound_interface(config: dict, tag: str) -> str | None:
    return outbound(config, tag).get("streamSettings", {}).get("sockopt", {}).get("interface")


def test_tun_mode_binds_direct_and_proxy_to_the_physical_interface(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN
    context.config.tun_name = "xray7"

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "eth0"
    assert bound_interface(config, profile.bean.display_name) == "eth0"
    # Собственный TUN среди кандидатов быть не должен: при пересборке конфига на
    # поднятом туннеле маршрут по умолчанию указывает именно на него.
    assert physical == [(None, ("xray7",))]


def test_binding_keeps_other_stream_settings_of_the_profile(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    stream = outbound(config, profile.bean.display_name)["streamSettings"]
    assert stream["security"] == "tls"
    assert stream["tlsSettings"] == {"serverName": "proxy.example.org"}


def test_system_proxy_mode_binds_nothing(context, profile, physical):
    """Без TUN маршрут по умолчанию и так ведёт в сеть — привязка только мешала бы."""
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") is None
    assert bound_interface(config, profile.bean.display_name) is None
    assert physical == []


def test_unknown_physical_interface_leaves_outbounds_unbound(context, profile, monkeypatch):
    context.config.proxy_mode = ProxyMode.TUN
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") is None


def test_vpn_profile_keeps_its_explicit_direct_interface(context, profile, physical, monkeypatch):
    profile.vpn_settings = VpnSettings(
        enabled=True, connection_name="corp", direct_interface="wlan9"
    )
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "wlan9"
    assert bound_interface(config, "vpn") == "tun0"
    assert physical == []


def test_vpn_profile_detects_interface_skipping_vpn_and_own_tun(
    context, profile, physical, monkeypatch
):
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
    context.config.tun_name = "xray7"

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "eth0"
    assert physical == [("tun0", ("xray7",))]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_profile_on_loopback_is_not_bound(context, physical, host):
    """Локальный обфускатор перед сервером слушает на loopback — через eth0 его не достать."""
    profile = make_profile(
        context, f"vless://11111111-1111-1111-1111-111111111111@{host}:443?security=tls#L"
    )
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    assert bound_interface(config, profile.bean.display_name) is None
    assert bound_interface(config, "direct") == "eth0"
