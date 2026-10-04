"""HTTP-проба через локальный inbound ядра: учётные данные и замер."""

from __future__ import annotations

import pytest
import requests

from src.core import http_probe
from src.core.http_probe import (
    ProbeCredentials,
    ProbeEndpoint,
    build_probe_inbound,
    measure_latency,
)

ENDPOINT = ProbeEndpoint(port=41001, credentials=ProbeCredentials("user", "p@ss/word"))


class FakeSession:
    """Отвечает по сценарию: код ответа или исключение на каждый запрос."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def head(self, url, **kwargs):
        self.calls.append((url, kwargs))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        response = requests.Response()
        response.status_code = step
        return response


@pytest.fixture
def session(monkeypatch):
    def install(script):
        fake = FakeSession(script)
        monkeypatch.setattr(http_probe.requests, "Session", lambda: fake)
        return fake

    return install


def test_generated_credentials_are_unique_and_non_empty():
    first = ProbeCredentials.generate()
    second = ProbeCredentials.generate()

    assert first.user and first.password
    assert first != second


def test_proxy_url_escapes_credentials():
    assert ENDPOINT.proxy_url == "http://user:p%40ss%2Fword@127.0.0.1:41001"


def test_probe_inbound_requires_accounts_and_listens_on_loopback():
    inbound = build_probe_inbound("probe-in-1", ENDPOINT)

    assert inbound == {
        "tag": "probe-in-1",
        "listen": "127.0.0.1",
        "port": 41001,
        "protocol": "http",
        "settings": {"accounts": [{"user": "user", "pass": "p@ss/word"}]},
    }


@pytest.mark.parametrize("credentials", [ProbeCredentials("", "x"), ProbeCredentials("x", "")])
def test_probe_inbound_is_not_built_without_credentials(credentials):
    with pytest.raises(ValueError, match="учётных данных"):
        build_probe_inbound("probe-in-1", ProbeEndpoint(port=41001, credentials=credentials))


def test_measure_latency_goes_through_the_endpoint_ignoring_environment(session):
    fake = session([204])

    latency = measure_latency(ENDPOINT, "http://example.com/generate_204", probes=1)

    assert latency >= 0
    assert fake.trust_env is False
    url, kwargs = fake.calls[0]
    assert url.startswith("http://example.com/generate_204?cb=")
    assert kwargs["proxies"] == {"http": ENDPOINT.proxy_url, "https": ENDPOINT.proxy_url}
    assert kwargs["allow_redirects"] is False


def test_measure_latency_appends_cache_buster_to_existing_query(session):
    fake = session([204])

    measure_latency(ENDPOINT, "http://example.com/?a=1", probes=1)

    assert fake.calls[0][0].startswith("http://example.com/?a=1&cb=")


def test_measure_latency_returns_median_of_successful_probes(session, monkeypatch):
    session([204, 204, 204])
    # Три замера: 10, 500 и 20 мс. Медиана отбрасывает выброс.
    ticks = iter([0, 10, 0, 500, 0, 20])
    monkeypatch.setattr(http_probe.time, "perf_counter_ns", lambda: next(ticks) * 1_000_000)

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) == 20


@pytest.mark.parametrize("status", [407, 500, 502, 503])
def test_measure_latency_treats_proxy_errors_as_failure(session, status):
    # 407 — неверные учётные данные inbound'а, 5xx — ядро не достучалось до сервера.
    session([status])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=1) == -1


def test_measure_latency_accepts_client_errors_from_the_target(session):
    # 403 от целевого сайта означает, что туннель работает.
    session([403])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=1) >= 0


def test_measure_latency_gives_up_after_the_first_failed_probe(session):
    # Мёртвый сервер не должен съедать таймаут трижды.
    fake = session([requests.exceptions.ConnectTimeout("timeout"), 204, 204])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) == -1
    assert len(fake.calls) == 1


def test_measure_latency_keeps_earlier_samples_when_a_later_probe_fails(session):
    fake = session([204, requests.exceptions.ReadTimeout("timeout"), 204])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) >= 0
    assert len(fake.calls) == 3
