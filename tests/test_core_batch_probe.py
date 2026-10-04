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
    split_accepted,
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
# Сборку проходят, а ядро отвергает: короткий ключ REALITY и неизвестный fingerprint.
VLESS_BAD_REALITY = (
    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=reality&pbk=abc&sni=a.example.com#BR"
)
VLESS_BAD_FINGERPRINT = (
    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=tls&sni=a.example.com&fp=nosuchfp#BF"
)
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


# --- отсев: один плохой профиль не должен ронять весь пакет ---


def fake_accepts(bad_ids: set[int], calls: list[int] | None = None):
    def accepts(chunk) -> bool:
        if calls is not None:
            calls.append(len(chunk))
        return not any(t.profile_id in bad_ids for t in chunk)

    return accepts


def numbered_targets(count: int) -> list[ProbeTarget]:
    return [ProbeTarget(i, {"protocol": "freedom"}) for i in range(1, count + 1)]


def test_split_accepted_keeps_everything_when_the_core_agrees():
    targets = numbered_targets(8)
    calls: list[int] = []

    accepted, rejected = split_accepted(targets, fake_accepts(set(), calls))

    assert accepted == targets
    assert rejected == []
    assert calls == [8]


def test_split_accepted_isolates_the_rejected_profiles_and_keeps_order():
    targets = numbered_targets(9)

    accepted, rejected = split_accepted(targets, fake_accepts({3, 8}))

    assert [t.profile_id for t in accepted] == [1, 2, 4, 5, 6, 7, 9]
    assert [t.profile_id for t in rejected] == [3, 8]


def test_split_accepted_halves_instead_of_checking_one_by_one():
    targets = numbered_targets(64)
    calls: list[int] = []

    split_accepted(targets, fake_accepts({40}, calls))

    # 1 проверка целого пакета и по две на каждом из 6 уровней деления.
    assert len(calls) == 13


def test_split_accepted_handles_an_empty_and_a_fully_rejected_batch():
    assert split_accepted([], fake_accepts(set())) == ([], [])

    targets = numbered_targets(3)
    accepted, rejected = split_accepted(targets, fake_accepts({1, 2, 3}))
    assert accepted == []
    assert rejected == targets


@needs_xray
@pytest.mark.parametrize("bad_link", [VLESS_BAD_REALITY, VLESS_BAD_FINGERPRINT])
def test_core_rejects_the_whole_batch_because_of_one_profile(bad_link):
    """Причина отсева: такой профиль проходит сборку, а ядро из-за него не стартует."""
    targets = [target(1, VLESS_WS), target(2, bad_link), target(3, TROJAN)]
    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)

    assert core_accepts(str(XRAY), config) is False


@needs_xray
def test_split_accepted_finds_what_the_real_core_rejects():
    targets = [
        target(1, VLESS_WS),
        target(2, VLESS_BAD_REALITY),
        target(3, TROJAN),
        target(4, VLESS_BAD_FINGERPRINT),
        target(5, HYSTERIA2),
    ]

    def accepts(chunk) -> bool:
        ports = list(range(41001, 41001 + len(chunk)))
        return core_accepts(str(XRAY), build_batch_probe_config(chunk, ports, CREDENTIALS))

    accepted, rejected = split_accepted(targets, accepts)

    assert [t.profile_id for t in accepted] == [1, 3, 5]
    assert [t.profile_id for t in rejected] == [2, 4]
