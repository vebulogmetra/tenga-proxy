from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.ui.app import TengaApp
from src.ui.main_window import MainWindow


def _make_app(profile: object | None) -> TengaApp:
    app = TengaApp.__new__(TengaApp)
    app._context = SimpleNamespace(
        config=SimpleNamespace(
            inbound_address="127.0.0.1",
            tun_name="xray0",
            tun_mtu=1500,
        ),
        profiles=SimpleNamespace(get_profile=Mock(return_value=profile)),
        xray_manager=SimpleNamespace(binary_path="/tmp/xray"),
    )
    return app


def test_create_latency_test_config_replaces_tun_inbound(monkeypatch):
    profile = SimpleNamespace(id=101)
    app = _make_app(profile)

    monkeypatch.setattr(
        app,
        "_create_config",
        lambda _profile: {
            "inbounds": [{"protocol": "tun", "tag": "tun-in"}],
            "outbounds": [{"protocol": "freedom", "tag": "proxy"}],
            "routing": {"rules": []},
        },
    )
    monkeypatch.setattr(app, "_reserve_latency_port_pair", lambda _host: 15080)

    result = app._create_latency_test_config(profile)

    assert result is not None
    config, socks_port = result

    assert socks_port == 15080
    assert all(inbound.get("protocol") != "tun" for inbound in config["inbounds"])
    protocols = [inbound.get("protocol") for inbound in config["inbounds"]]
    assert protocols == ["socks", "http"]
    ports = [inbound.get("port") for inbound in config["inbounds"]]
    assert ports == [15080, 15081]


def test_test_profile_latency_uses_temp_manager_and_stops(monkeypatch):
    profile = SimpleNamespace(id=55)
    app = _make_app(profile)

    monkeypatch.setattr(
        app,
        "_create_latency_test_config",
        lambda _profile: (
            {
                "log": {"loglevel": "warning"},
                "inbounds": [],
                "outbounds": [],
                "routing": {"rules": []},
            },
            17080,
        ),
    )

    created = []

    class FakeXrayManager:
        def __init__(self, binary_path=None):
            self.binary_path = binary_path
            self.stop_called = False
            self.started_with = None
            created.append(self)

        def start(self, config):
            self.started_with = config
            return True, ""

        def test_delay_realistic(self, **kwargs):
            assert kwargs["proxy_address"] == "127.0.0.1"
            assert kwargs["proxy_port"] == 17080
            assert kwargs["probes"] == 3
            return 321

        def stop(self):
            self.stop_called = True
            return True, ""

    monkeypatch.setattr("src.core.xray_manager.XrayManager", FakeXrayManager)

    result = app.test_profile_latency(profile_id=55, timeout_ms=3000, probes=3)

    assert result == 321
    assert len(created) == 1
    assert created[0].stop_called is True
    assert created[0].started_with is not None


def test_test_profile_latency_returns_minus_one_for_missing_profile():
    app = _make_app(profile=None)
    assert app.test_profile_latency(profile_id=404) == -1


def test_main_window_run_profile_latency_uses_callback():
    window = MainWindow.__new__(MainWindow)
    window._on_test_latency = lambda profile_id: 77 if profile_id == 10 else -1

    assert window._run_profile_latency_test(10) == 77
    assert window._run_profile_latency_test(11) == -1
