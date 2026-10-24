"""Что служба от имени SYSTEM согласна запустить."""

from __future__ import annotations

import copy

import pytest

from src.winsvc.policy import PolicyError, sanitize_core_config

BASE = {
    "log": {"loglevel": "warning", "access": "C:/Windows/evil.txt", "error": "C:/x.log"},
    "inbounds": [
        {"tag": "tun-in", "protocol": "tun", "settings": {"name": "xray0"}},
        {"tag": "socks-in", "protocol": "mixed", "listen": "127.0.0.1", "port": 2080},
    ],
    "outbounds": [
        {
            "tag": "proxy",
            "protocol": "vless",
            "settings": {},
            "streamSettings": {"network": "ws", "wsSettings": {"path": "/ws"}},
        },
        {"tag": "direct", "protocol": "freedom"},
    ],
    "routing": {"rules": []},
}


def config(**changes):
    result = copy.deepcopy(BASE)
    result.update(changes)
    return result


def test_valid_config_passes_and_log_paths_are_dropped():
    result = sanitize_core_config(config())

    assert "access" not in result["log"]
    assert "error" not in result["log"]
    assert result["log"]["loglevel"] == "warning"


def test_transport_path_is_not_a_file():
    sanitize_core_config(config())


def test_inbound_on_all_interfaces_is_refused():
    bad = config()
    bad["inbounds"][1]["listen"] = "0.0.0.0"

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_unknown_inbound_protocol_is_refused():
    bad = config()
    bad["inbounds"].append({"tag": "x", "protocol": "vless", "listen": "127.0.0.1", "port": 1})

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_unix_socket_inbound_is_refused():
    bad = config()
    bad["inbounds"][1]["listen"] = "C:\\Windows\\Temp\\s.sock"

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


@pytest.mark.parametrize("key", ["certificateFile", "keyFile", "masterKeyLog"])
def test_file_keys_are_refused_anywhere(key):
    bad = config()
    bad["outbounds"][0]["streamSettings"]["tlsSettings"] = {"certificates": [{key: "C:/x"}]}

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_external_geo_file_outside_assets_is_refused():
    bad = config(
        routing={"rules": [{"domain": ["ext:..\\..\\secret.dat:x"], "outboundTag": "proxy"}]}
    )

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_client_api_inbound_is_dropped():
    with_api = config()
    with_api["inbounds"].append({"tag": "api", "protocol": "dokodemo-door", "listen": "127.0.0.1"})

    result = sanitize_core_config(with_api)

    assert all(inbound.get("tag") != "api" for inbound in result["inbounds"])


def test_session_validator_violations_are_refused():
    bad = config(outbounds=[{"tag": "direct", "protocol": "freedom"}])

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_input_is_not_modified():
    original = config()
    snapshot = copy.deepcopy(original)

    sanitize_core_config(original)

    assert original == snapshot


def test_inbound_without_listen_is_refused():
    bad = config()
    del bad["inbounds"][1]["listen"]

    with pytest.raises(PolicyError):
        sanitize_core_config(bad)


def test_config_built_by_the_gui_passes(tmp_path, monkeypatch):
    """Политика не отвергает то, что собирает сам GUI в режиме TUN."""
    from src.core import config_builder, platform_info
    from src.core.config_builder import build_session_config
    from src.core.health_probe import attach_health_inbound
    from src.core.http_probe import ProbeCredentials, ProbeEndpoint
    from src.db.config import ProxyMode
    from tests.support.session import make_context, make_profile, use_bundled_geo

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    use_bundled_geo(monkeypatch)
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "Ethernet")
    context = make_context(tmp_path)
    context.config.proxy_mode = ProxyMode.TUN
    session = build_session_config(context, make_profile(context))
    attach_health_inbound(
        session, ProbeEndpoint(port=20811, credentials=ProbeCredentials("u", "p"))
    )

    result = sanitize_core_config(session)

    assert any(inbound["protocol"] == "tun" for inbound in result["inbounds"])
