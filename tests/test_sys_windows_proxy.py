"""Системный прокси Windows: значения реестра и уведомление WinINet."""

from __future__ import annotations

import pytest

from src.sys.windows import proxy


class FakeRegistry:
    def __init__(self):
        self.values: dict[str, object] = {}

    def write(self, values: dict[str, object]) -> None:
        self.values.update(values)


def test_values_for_mixed_port():
    values = proxy.proxy_values(http_port=2080, socks_port=2080)

    assert values["ProxyEnable"] == 1
    assert values["ProxyServer"] == "127.0.0.1:2080"
    assert "<local>" in values["ProxyOverride"]
    assert "localhost" in values["ProxyOverride"]


def test_http_port_wins_when_ports_differ():
    assert proxy.proxy_values(http_port=8080, socks_port=1080)["ProxyServer"] == "127.0.0.1:8080"


def test_socks_only_uses_socks_scheme():
    assert proxy.proxy_values(http_port=0, socks_port=1080)["ProxyServer"] == "socks=127.0.0.1:1080"


def test_set_writes_registry_and_notifies(monkeypatch):
    registry = FakeRegistry()
    notified = []

    assert proxy.set_system_proxy(2080, 2080, registry=registry, notify=lambda: notified.append(1))
    assert registry.values["ProxyEnable"] == 1
    assert notified == [1]


def test_nothing_to_set_returns_false():
    assert proxy.set_system_proxy(0, 0, registry=FakeRegistry(), notify=lambda: None) is False


def test_clear_disables_proxy():
    registry = FakeRegistry()

    assert proxy.clear_system_proxy(registry=registry, notify=lambda: None)
    assert registry.values == {"ProxyEnable": 0}


def test_registry_failure_returns_false():
    class Broken:
        def write(self, values):
            raise OSError("access denied")

    assert proxy.set_system_proxy(2080, 2080, registry=Broken(), notify=lambda: None) is False


@pytest.mark.windows
def test_real_registry_roundtrip():
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, proxy.KEY_PATH) as key:
        before = winreg.QueryValueEx(key, "ProxyEnable")[0]
    try:
        assert proxy.set_system_proxy(2080, 2080)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, proxy.KEY_PATH) as key:
            assert winreg.QueryValueEx(key, "ProxyServer")[0] == "127.0.0.1:2080"
    finally:
        proxy._apply({"ProxyEnable": before}, None, None)
