from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import requests

from src.core.xray_manager import XrayManager


def _make_running_manager(monkeypatch) -> XrayManager:
    # Версия ядра читается в конструкторе и лезет к бинарнику, которого в
    # тестах нет. Подменяется метод экземпляра, поэтому `self` в сигнатуре
    # обязателен, хотя и не используется.
    monkeypatch.setattr(XrayManager, "_fetch_version", lambda self: None)  # noqa: ARG005
    manager = XrayManager(binary_path="xray")
    manager._process = Mock()
    manager._process.poll.return_value = None
    return manager


def test_test_delay_realistic_returns_minus_one_when_manager_not_running(monkeypatch):
    monkeypatch.setattr(XrayManager, "_fetch_version", lambda self: None)  # noqa: ARG005
    manager = XrayManager(binary_path="xray")

    delay_ms = manager.test_delay_realistic(
        proxy_address="127.0.0.1",
        proxy_port=1080,
        timeout=3000,
        probes=3,
    )

    assert delay_ms == -1


def test_test_delay_realistic_uses_median_and_ignores_outlier(monkeypatch):
    manager = _make_running_manager(monkeypatch)

    perf_values = [
        1_000_000_000,
        1_020_000_000,  # 20 ms
        2_000_000_000,
        2_120_000_000,  # 120 ms
        3_000_000_000,
        3_980_000_000,  # 980 ms (outlier)
    ]
    perf_iter = iter(perf_values)
    monkeypatch.setattr("src.core.xray_manager.time.perf_counter_ns", lambda: next(perf_iter))

    def fake_head(*args, **kwargs):
        return SimpleNamespace(status_code=204)

    monkeypatch.setattr("src.core.xray_manager.requests.head", fake_head)

    delay_ms = manager.test_delay_realistic(
        proxy_address="127.0.0.1",
        proxy_port=1080,
        timeout=3000,
        probes=3,
    )

    assert delay_ms == 120


def test_test_delay_realistic_calls_http_proxy_with_cache_buster(monkeypatch):
    manager = _make_running_manager(monkeypatch)
    monkeypatch.setattr(
        "src.core.xray_manager.time.perf_counter_ns",
        Mock(side_effect=[1_000_000_000, 1_050_000_000, 2_000_000_000, 2_050_000_000]),
    )

    calls = []

    def fake_head(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=204)

    monkeypatch.setattr("src.core.xray_manager.requests.head", fake_head)

    delay_ms = manager.test_delay_realistic(
        proxy_address="127.0.0.1",
        proxy_port=1080,
        timeout=2000,
        probes=2,
    )

    assert delay_ms == 50
    assert len(calls) == 2

    first_url, first_kwargs = calls[0]
    second_url, second_kwargs = calls[1]

    assert "generate_204" in first_url
    assert "cb=" in first_url
    assert "cb=" in second_url
    assert first_url != second_url
    assert first_kwargs["proxies"] == {
        "http": "http://127.0.0.1:1081",
        "https": "http://127.0.0.1:1081",
    }
    assert first_kwargs["allow_redirects"] is False
    assert isinstance(first_kwargs["timeout"], float)
    assert second_kwargs["proxies"] == first_kwargs["proxies"]


def test_test_delay_realistic_returns_minus_one_if_no_successful_probes(monkeypatch):
    manager = _make_running_manager(monkeypatch)
    monkeypatch.setattr(
        "src.core.xray_manager.time.perf_counter_ns",
        Mock(side_effect=[1_000_000_000, 1_200_000_000, 2_000_000_000, 2_200_000_000]),
    )

    def fake_head(*args, **kwargs):
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr("src.core.xray_manager.requests.head", fake_head)

    delay_ms = manager.test_delay_realistic(
        proxy_address="127.0.0.1",
        proxy_port=1080,
        timeout=1000,
        probes=2,
    )

    assert delay_ms == -1
