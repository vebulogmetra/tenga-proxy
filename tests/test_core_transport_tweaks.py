"""Фрагментация TLS и mux поверх proxy-outbound'а."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.core.config_builder import build_latency_probe_config, build_session_config
from src.core.context import init_context
from src.core.transport_tweaks import apply_mux, apply_tls_fragment, is_mux_eligible
from src.db.config import TlsFragmentSettings
from src.db.data_store import DataStore
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
UUID = "11111111-1111-1111-1111-111111111111"
VLESS_TLS = f"vless://{UUID}@127.0.0.1:443?type=tcp&security=tls&sni=a.example.com#T"
VLESS_WS = f"vless://{UUID}@127.0.0.1:443?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
VLESS_VISION = (
    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=reality&sni=a.example.com"
    "&pbk=7xhH4b_VkliBxGULljcyPOH-bYUA2dl-XAdZAsfhk04&sid=ab&flow=xtls-rprx-vision#V"
)
VLESS_XHTTP = f"vless://{UUID}@127.0.0.1:443?type=xhttp&security=tls&sni=a.example.com#X"
TROJAN = "trojan://pass123@127.0.0.1:443?type=tcp&sni=a.example.com#TR"
HYSTERIA2 = "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com#H"
SHADOWSOCKS = "ss://YWVzLTI1Ni1nY206cGFzcw@127.0.0.1:8388#SS"
FRAGMENT_ON = TlsFragmentSettings(enabled=True)


def outbound_of(link: str) -> dict:
    bean = parse_link(link)
    assert bean is not None, link
    return bean.build_outbound()


# --- TlsFragmentSettings ---


def test_fragment_is_off_by_default():
    assert DataStore().tls_fragment.enabled is False


def test_fragment_settings_survive_serialization():
    store = DataStore()
    store.tls_fragment = TlsFragmentSettings(
        enabled=True, packets="1-3", length="50-100", delay="5"
    )
    restored = DataStore.from_dict(store.to_dict())
    assert restored.tls_fragment == store.tls_fragment


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ("packets", "tlshello", True),
        ("packets", "TLSHello", True),
        ("packets", "1-3", True),
        ("packets", "0-3", False),
        ("packets", "hello", False),
        ("length", "100-200", True),
        ("length", "40", True),
        ("length", "0-100", False),
        ("length", "200-100", False),
        ("length", "20000", False),
        ("delay", "0", True),
        ("delay", "10-20", True),
        ("delay", "2000", False),
        ("delay", "", False),
    ],
)
def test_fragment_field_validation(field, value, valid):
    check = getattr(TlsFragmentSettings, f"is_valid_{field}")
    assert check(value) is valid


def test_sanitized_replaces_invalid_fields_with_defaults():
    dirty = TlsFragmentSettings(enabled=True, packets="oops", length=" 50-100 ", delay="-1")
    assert dirty.sanitized() == TlsFragmentSettings(
        enabled=True, packets="tlshello", length="50-100", delay="10-20"
    )


# --- apply_tls_fragment ---


@pytest.mark.parametrize("link", [VLESS_TLS, VLESS_WS, VLESS_VISION, VLESS_XHTTP, TROJAN])
def test_fragment_mask_is_added_to_tls_outbounds(link):
    outbound = outbound_of(link)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert outbound["streamSettings"]["finalmask"] == {
        "tcp": [
            {
                "type": "fragment",
                "settings": {"packets": "tlshello", "length": "100-200", "delay": "10-20"},
            }
        ]
    }


def test_fragment_is_skipped_when_disabled():
    outbound = outbound_of(VLESS_TLS)
    apply_tls_fragment(outbound, TlsFragmentSettings(enabled=False))
    assert "finalmask" not in outbound["streamSettings"]


def test_fragment_is_skipped_for_quic():
    """hysteria2 — это QUIC: tcp-масок там нет."""
    outbound = outbound_of(HYSTERIA2)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert "finalmask" not in outbound["streamSettings"]


def test_fragment_is_skipped_without_tls():
    outbound = outbound_of(SHADOWSOCKS)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert "finalmask" not in outbound.get("streamSettings", {})


def test_fragment_does_not_touch_profile_tcp_masks():
    outbound = outbound_of(VLESS_TLS)
    own = {"tcp": [{"type": "sudoku", "settings": {}}], "udp": [{"type": "noise"}]}
    outbound["streamSettings"]["finalmask"] = json.loads(json.dumps(own))
    apply_tls_fragment(outbound, FRAGMENT_ON)
    assert outbound["streamSettings"]["finalmask"] == own


def test_fragment_keeps_other_finalmask_keys():
    outbound = outbound_of(VLESS_TLS)
    outbound["streamSettings"]["finalmask"] = {"udp": [{"type": "noise"}]}
    apply_tls_fragment(outbound, FRAGMENT_ON)
    mask = outbound["streamSettings"]["finalmask"]
    assert mask["udp"] == [{"type": "noise"}]
    assert mask["tcp"][0]["type"] == "fragment"


# --- mux ---


@pytest.mark.parametrize(
    ("link", "eligible"),
    [
        (VLESS_TLS, True),
        (VLESS_WS, True),
        (TROJAN, True),
        (VLESS_VISION, False),
        (VLESS_XHTTP, False),
        (HYSTERIA2, False),
        (SHADOWSOCKS, False),
    ],
    ids=["vless-tcp", "vless-ws", "trojan", "vision", "xhttp", "hysteria2", "shadowsocks"],
)
def test_mux_eligibility(link, eligible):
    assert is_mux_eligible(outbound_of(link)) is eligible


def test_mux_block_skips_udp_443():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=True, concurrency=8)
    assert outbound["mux"] == {
        "enabled": True,
        "concurrency": 8,
        "xudpConcurrency": 16,
        "xudpProxyUDP443": "skip",
    }


def test_mux_is_silently_skipped_on_ineligible_outbound():
    outbound = outbound_of(VLESS_VISION)
    apply_mux(outbound, enabled=True)
    assert "mux" not in outbound


def test_mux_is_skipped_when_disabled():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=False)
    assert "mux" not in outbound


def test_out_of_range_concurrency_falls_back_to_default():
    outbound = outbound_of(VLESS_WS)
    apply_mux(outbound, enabled=True, concurrency=0)
    assert outbound["mux"]["concurrency"] == 8


# --- через билдер конфига ---


@pytest.fixture
def context(tmp_path):
    return init_context(config_dir=tmp_path)


def entry(link: str) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None
    return ProfileEntry(id=1, group_id=0, bean=bean)


def test_session_config_has_no_tweaks_by_default(context):
    config = build_session_config(context, entry(VLESS_WS))
    assert config is not None
    proxy = config["outbounds"][0]
    assert "mux" not in proxy
    assert "finalmask" not in proxy["streamSettings"]


def test_session_and_probe_configs_carry_the_same_tweaks(context):
    """Замер задержки обязан идти с теми же tweaks, что и рабочее подключение."""
    context.config.tls_fragment.enabled = True
    context.config.mux_default_on = True
    profile = entry(VLESS_WS)

    session = build_session_config(context, profile)
    probe = build_latency_probe_config(context, profile)

    assert session is not None and probe is not None
    for config in (session, probe[0]):
        proxy = config["outbounds"][0]
        assert proxy["mux"]["enabled"] is True
        assert proxy["streamSettings"]["finalmask"]["tcp"][0]["type"] == "fragment"


@pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)
@pytest.mark.parametrize(
    "link",
    [VLESS_TLS, VLESS_WS, VLESS_VISION, VLESS_XHTTP, TROJAN, HYSTERIA2, SHADOWSOCKS],
    ids=["vless-tcp", "vless-ws", "vision", "xhttp", "trojan", "hysteria2", "shadowsocks"],
)
def test_outbound_with_tweaks_is_accepted_by_xray(link, tmp_path):
    outbound = outbound_of(link)
    apply_tls_fragment(outbound, FRAGMENT_ON)
    apply_mux(outbound, enabled=True)
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"port": 10800, "protocol": "socks", "settings": {}}],
        "outbounds": [outbound],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    result = subprocess.run(
        [str(XRAY), "-test", "-config", str(path)], capture_output=True, text=True, timeout=60
    )
    assert "Configuration OK" in result.stdout + result.stderr
