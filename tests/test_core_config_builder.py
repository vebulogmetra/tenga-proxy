"""Characterisation tests for xray config building.

The builder moved out of TengaApp into src.core.config_builder; these tests pin
the generated structure so the move stays behaviour-preserving.
"""

from __future__ import annotations

import json

import pytest

from src.core.config_builder import (
    build_latency_probe_config,
    build_session_config,
    reserve_latency_port_pair,
)
from src.core.context import init_context
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

VLESS_LINK = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443"
    "?type=tcp&security=tls&sni=example.com#Test%20Profile"
)


@pytest.fixture
def context(tmp_path):
    return init_context(config_dir=tmp_path)


@pytest.fixture
def profile(context):
    bean = parse_link(VLESS_LINK)
    assert bean is not None
    entry = ProfileEntry(id=1, group_id=0, bean=bean)
    context.profiles.profiles[1] = entry
    return entry


def test_session_config_has_inbounds_and_tagged_outbounds(context, profile):
    config = build_session_config(context, profile)

    assert config is not None
    assert config["inbounds"]
    # первый outbound — сам профиль (тег = имя профиля), затем прямой выход
    assert config["outbounds"][0]["tag"] == profile.bean.display_name
    assert config["outbounds"][0]["protocol"] == "vless"
    assert {o.get("tag") for o in config["outbounds"]} >= {profile.bean.display_name, "direct"}
    # сериализуемо: ядро получает конфиг как JSON
    json.dumps(config)


def test_session_config_returns_none_without_profile(context):
    assert build_session_config(context, None) is None


def test_latency_probe_config_uses_system_proxy_inbounds(context, profile):
    result = build_latency_probe_config(context, profile)

    assert result is not None
    config, socks_port = result
    assert isinstance(socks_port, int)
    assert 20000 <= socks_port < 65000
    protocols = {inbound["protocol"] for inbound in config["inbounds"]}
    assert protocols <= {"socks", "http"}
    assert "tun" not in protocols
    ports = {inbound["port"] for inbound in config["inbounds"]}
    assert ports == {socks_port, socks_port + 1}


def test_reserve_latency_port_pair_returns_free_consecutive_ports():
    import socket

    port = reserve_latency_port_pair("127.0.0.1")

    for candidate in (port, port + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", candidate))
        finally:
            sock.close()
