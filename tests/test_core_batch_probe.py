"""Пакетный замер задержки: один процесс ядра на весь набор профилей."""

from __future__ import annotations

import http.server
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import requests

from src.core import batch_probe
from src.core.batch_probe import (
    BatchCore,
    ProbeTarget,
    build_batch_probe_config,
    build_probe_outbound,
    core_accepts,
    measure_targets,
    probe_profiles,
    probe_targets,
    reserve_ports,
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


# --- запуск ядра и замер ---

FREEDOM = {"protocol": "freedom"}
BLACKHOLE = {"protocol": "blackhole"}


class _Site(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def local_site():
    """Локальный сайт вместо интернета: замер идёт ядро → freedom → 127.0.0.1."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/generate_204"
    server.shutdown()
    server.server_close()


@pytest.fixture
def core_starts(monkeypatch):
    """Сколько раз запускался процесс ядра (проверки `-test` не в счёт)."""
    starts: list[list[str]] = []
    real_popen = batch_probe.subprocess.Popen

    def counting_popen(args, **kwargs):
        # subprocess.run тоже идёт через Popen: проверки `-test` отсеиваем.
        if "run" in args:
            starts.append(list(args))
        return real_popen(args, **kwargs)

    monkeypatch.setattr(batch_probe.subprocess, "Popen", counting_popen)
    return starts


def test_reserve_ports_returns_distinct_free_ports():
    ports = reserve_ports(20)

    assert len(set(ports)) == 20
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))


def test_measure_targets_reports_results_as_they_arrive(monkeypatch):
    delays = {41001: 0.3, 41002: 0.0, 41003: 0.1}

    def fake_measure(endpoint, url, **_kwargs):
        time.sleep(delays[endpoint.port])
        return endpoint.port

    monkeypatch.setattr(batch_probe, "measure_latency", fake_measure)
    order: list[int] = []

    measure_targets(
        numbered_targets(3),
        [41001, 41002, 41003],
        CREDENTIALS,
        url="http://example.com/",
        on_result=lambda profile_id, _latency: order.append(profile_id),
    )

    assert order == [2, 3, 1]


def test_measure_targets_turns_an_unexpected_error_into_minus_one(monkeypatch):
    def broken(endpoint, url, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(batch_probe, "measure_latency", broken)
    results: dict[int, int] = {}

    measure_targets(
        numbered_targets(2),
        [41001, 41002],
        CREDENTIALS,
        url="http://example.com/",
        on_result=results.__setitem__,
    )

    assert results == {1: -1, 2: -1}


@needs_xray
def test_one_core_process_measures_the_whole_batch(local_site, core_starts):
    targets = [ProbeTarget(i, FREEDOM) for i in range(1, 101)]
    results: dict[int, int] = {}

    probe_targets(
        targets,
        binary_path=str(XRAY),
        on_result=results.__setitem__,
        url=local_site,
        probes=1,
    )

    assert len(core_starts) == 1
    assert sorted(results) == list(range(1, 101))
    assert all(latency >= 0 for latency in results.values())


@needs_xray
def test_dead_and_rejected_profiles_get_minus_one_and_the_rest_are_measured(
    local_site, core_starts
):
    targets = [
        ProbeTarget(1, FREEDOM),
        target(2, VLESS_BAD_REALITY),
        ProbeTarget(3, BLACKHOLE),
        ProbeTarget(4, FREEDOM),
    ]
    results: dict[int, int] = {}

    probe_targets(
        targets,
        binary_path=str(XRAY),
        on_result=results.__setitem__,
        url=local_site,
        probes=1,
    )

    assert results[2] == -1  # ядро отвергло профиль
    assert results[3] == -1  # ядро приняло, но сервер не отвечает
    assert results[1] >= 0
    assert results[4] >= 0
    assert len(core_starts) == 1


@needs_xray
def test_probe_inbound_answers_407_without_valid_credentials(local_site):
    ports = reserve_ports(1)
    config = build_batch_probe_config([ProbeTarget(1, FREEDOM)], ports, CREDENTIALS)

    with BatchCore(str(XRAY), config) as core:
        assert core.wait_ready(ports)
        statuses = []
        for proxy in (
            f"http://127.0.0.1:{ports[0]}",
            f"http://probe:wrong@127.0.0.1:{ports[0]}",
            f"http://probe:secret@127.0.0.1:{ports[0]}",
        ):
            with requests.Session() as session:
                session.trust_env = False
                response = session.head(local_site, proxies={"http": proxy}, timeout=5)
                statuses.append(response.status_code)

    assert statuses == [407, 407, 204]


def test_batch_core_cleans_up_its_config_file(monkeypatch):
    written: list[Path] = []
    real_write = batch_probe._write_config

    def spy(config):
        path = real_write(config)
        written.append(path)
        return path

    monkeypatch.setattr(batch_probe, "_write_config", spy)

    with BatchCore("/nonexistent/xray", {"inbounds": []}) as core:
        assert written[0].exists()
        assert core.wait_ready([41001], timeout=0.2) is False

    assert not written[0].exists()


def test_every_profile_gets_minus_one_when_the_core_does_not_start(monkeypatch):
    # Проверку `-test` ядро «прошло», а процесс завершается сразу после запуска.
    monkeypatch.setattr(batch_probe, "core_accepts", lambda *_: True)
    results: dict[int, int] = {}

    probe_targets(
        numbered_targets(3),
        binary_path="false",
        on_result=results.__setitem__,
        url="http://example.com/",
    )

    assert results == {1: -1, 2: -1, 3: -1}


def test_large_sets_are_measured_in_several_batches(monkeypatch):
    batches: list[list[int]] = []
    monkeypatch.setattr(batch_probe, "MAX_BATCH_SIZE", 2)
    monkeypatch.setattr(
        batch_probe,
        "_probe_batch",
        lambda targets, **_kwargs: batches.append([t.profile_id for t in targets]),
    )

    probe_targets(numbered_targets(5), binary_path="xray", on_result=lambda *_: None)

    assert batches == [[1, 2], [3, 4], [5]]


def test_probe_profiles_reports_unbuildable_profiles_and_measures_the_rest(monkeypatch):
    measured: list[int] = []

    def fake_probe_targets(targets, *, on_result, **_kwargs):
        for item in targets:
            measured.append(item.profile_id)
            on_result(item.profile_id, 42)

    monkeypatch.setattr(batch_probe, "probe_targets", fake_probe_targets)
    results: dict[int, int] = {}

    probe_profiles(
        [entry(1, VLESS_WS), entry(2, VLESS_H2), entry(3, TROJAN)],
        settings=DataStore(),
        binary_path="xray",
        on_result=results.__setitem__,
    )

    assert measured == [1, 3]
    assert results == {1: 42, 2: -1, 3: 42}
