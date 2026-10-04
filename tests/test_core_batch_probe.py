"""Пакетный замер задержки: один процесс ядра на весь набор профилей."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.core.batch_probe import (
    ProbeTarget,
    build_batch_probe_config,
    build_probe_outbound,
    core_accepts,
)
from src.core.http_probe import ProbeCredentials
from src.db.config import TlsFragmentSettings
from src.db.data_store import DataStore
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

UUID = "11111111-1111-1111-1111-111111111111"
VLESS_WS = f"vless://{UUID}@127.0.0.1:443?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
TROJAN = "trojan://pass123@127.0.0.1:443?type=tcp&sni=a.example.com#TR"
HYSTERIA2 = "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com#H"
# Транспорт h2 ядро удалило: bean сам сообщает об ошибке сборки.
VLESS_H2 = f"vless://{UUID}@127.0.0.1:443?type=h2&security=tls&sni=a.example.com#H2"
CREDENTIALS = ProbeCredentials("probe", "secret")


def entry(profile_id: int, link: str) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None, link
    return ProfileEntry(id=profile_id, group_id=0, bean=bean)


def target(profile_id: int, link: str) -> ProbeTarget:
    outbound = build_probe_outbound(entry(profile_id, link), DataStore())
    assert outbound is not None, link
    return ProbeTarget(profile_id, outbound)


# --- outbound одного профиля ---


def test_probe_outbound_applies_the_same_tweaks_as_a_session():
    settings = DataStore()
    settings.tls_fragment = TlsFragmentSettings(enabled=True)

    outbound = build_probe_outbound(entry(1, VLESS_WS), settings)

    masks = outbound["streamSettings"]["finalmask"]["tcp"]
    assert masks[0]["type"] == "fragment"


def test_probe_outbound_is_none_for_a_profile_with_a_build_error():
    assert build_probe_outbound(entry(1, VLESS_H2), DataStore()) is None


def test_probe_outbound_is_none_when_the_bean_raises():
    class Broken:
        def build_core_obj_xray(self):
            raise RuntimeError("boom")

    profile = ProfileEntry(id=1, group_id=0, bean=Broken())  # type: ignore[arg-type]

    assert build_probe_outbound(profile, DataStore()) is None


# --- пакетный конфиг ---


def test_batch_config_pairs_every_inbound_with_its_own_outbound():
    targets = [target(7, VLESS_WS), target(9, TROJAN)]

    config = build_batch_probe_config(targets, [41001, 41002], CREDENTIALS)

    assert [i["tag"] for i in config["inbounds"]] == ["probe-in-1", "probe-in-2"]
    assert [i["port"] for i in config["inbounds"]] == [41001, 41002]
    assert [o["tag"] for o in config["outbounds"]] == ["proxy-1", "proxy-2"]
    assert [o["protocol"] for o in config["outbounds"]] == ["vless", "trojan"]
    assert config["routing"]["rules"] == [
        {"type": "field", "inboundTag": ["probe-in-1"], "outboundTag": "proxy-1"},
        {"type": "field", "inboundTag": ["probe-in-2"], "outboundTag": "proxy-2"},
    ]


def test_every_probe_inbound_is_an_authenticated_http_proxy_on_loopback():
    targets = [target(1, VLESS_WS), target(2, TROJAN), target(3, HYSTERIA2)]

    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)

    for inbound in config["inbounds"]:
        assert inbound["protocol"] == "http"
        assert inbound["listen"] == "127.0.0.1"
        assert inbound["settings"]["accounts"] == [{"user": "probe", "pass": "secret"}]


def test_batch_config_is_not_built_without_credentials():
    with pytest.raises(ValueError, match="учётных данных"):
        build_batch_probe_config([target(1, TROJAN)], [41001], ProbeCredentials("", ""))


def test_batch_config_does_not_touch_the_source_outbounds():
    source = target(1, TROJAN)
    before = dict(source.outbound)

    build_batch_probe_config([source], [41001], CREDENTIALS)

    assert source.outbound == before


def test_batch_config_requires_a_port_for_every_target():
    with pytest.raises(ValueError, match="портов"):
        build_batch_probe_config([target(1, TROJAN), target(2, TROJAN)], [41001], CREDENTIALS)


# --- схему знает только ядро ---


@needs_xray
def test_core_accepts_a_batch_of_mixed_protocols():
    targets = [target(1, VLESS_WS), target(2, TROJAN), target(3, HYSTERIA2)]
    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)

    assert core_accepts(str(XRAY), config) is True


@needs_xray
def test_core_rejects_a_batch_with_an_unknown_protocol():
    broken = ProbeTarget(1, {"protocol": "no-such-protocol", "settings": {}})
    config = build_batch_probe_config([broken], [41001], CREDENTIALS)

    assert core_accepts(str(XRAY), config) is False
