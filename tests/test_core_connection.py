"""Tests for the GTK-free connection service."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from src.core.connection import ConnectionService


@dataclass
class FakeVpn:
    enabled: bool = False
    connection_name: str = "my-vpn"
    auto_connect: bool = False


@dataclass
class FakeProfile:
    id: int = 1
    name: str = "P"
    vpn_settings: FakeVpn | None = None
    routing_settings: object | None = None
    bean: object = field(default_factory=lambda: MagicMock(server_address="1.2.3.4"))


def make_context(tmp_path, profile):
    context = MagicMock()
    context.config_dir = tmp_path
    context.profiles.get_profile.return_value = profile
    context.xray_manager.start.return_value = (True, "")
    context.xray_manager.stop.return_value = (True, "")
    context.config.proxy_mode = "system_proxy"
    context.config.inbound_socks_port = 2080
    context.config.tun_name = "xray0"
    context.proxy_state.is_running = False
    context.monitor = None
    return context


def test_connect_missing_profile_reports_the_error(tmp_path):
    context = make_context(tmp_path, None)
    result = ConnectionService(context).connect(7)
    assert not result.ok
    assert "не найден" in result.error


def test_connect_starts_xray_and_marks_the_state(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    result = ConnectionService(context).connect(1)
    assert result.ok
    context.xray_manager.start.assert_called_once()
    context.proxy_state.set_running.assert_called_once()


def test_connect_writes_the_config_for_debugging(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    ConnectionService(context).connect(1)
    assert (tmp_path / "current_config.json").exists()


def test_connect_reports_the_xray_error(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.start.return_value = (False, "binary not found")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    result = ConnectionService(context).connect(1)
    assert not result.ok
    assert result.error == "binary not found"
    context.proxy_state.set_running.assert_not_called()


def test_connect_without_a_config_stops_early(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: None)
    result = ConnectionService(context).connect(1)
    assert not result.ok
    context.xray_manager.start.assert_not_called()


def test_tun_route_failure_rolls_the_start_back(tmp_path, monkeypatch):
    """Маршруты не легли — xray не должен остаться запущенным."""
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = "tun"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr(
        "src.core.connection.apply_tun_routes", lambda *_: (False, None, "no permission")
    )
    result = ConnectionService(context).connect(1)
    assert not result.ok
    assert "no permission" in result.error
    context.xray_manager.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()


def test_vpn_is_connected_before_the_proxy_when_asked(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    calls = []
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: False)
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda n: (calls.append(n), True)[1])
    ConnectionService(context).connect(1)
    assert calls == ["my-vpn"]
    assert context.proxy_state.vpn_auto_connected is True


def test_an_already_active_vpn_is_not_touched(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: True)
    called = []
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda n: called.append(n))
    ConnectionService(context).connect(1)
    assert called == []


def test_a_failing_vpn_does_not_block_the_proxy(tmp_path, monkeypatch):
    """VPN — вспомогательный шаг: прокси должен подняться и без него."""
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: False)
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda _n: False)
    assert ConnectionService(context).connect(1).ok


def test_a_disabled_vpn_is_never_started(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=False, auto_connect=True))
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    called = []
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda n: called.append(n))
    ConnectionService(context).connect(1)
    assert called == []


def test_connect_while_running_disconnects_first(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 5
    context.proxy_state.started_mode = "system_proxy"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    ConnectionService(context).connect(1)
    context.xray_manager.stop.assert_called_once()


def test_disconnect_stops_xray_and_clears_the_proxy(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.started_mode = "system_proxy"
    context.proxy_state.started_profile_id = -1
    cleared = []
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: cleared.append(1))
    result = ConnectionService(context).disconnect()
    assert result.ok
    context.xray_manager.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()
    assert cleared == [1]


def test_disconnect_survives_a_failing_vpn_step(tmp_path, monkeypatch):
    """Падение отключения VPN не должно оставить xray работающим."""
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system_proxy"
    context.proxy_state.vpn_auto_connected = True

    def boom(_name):
        raise RuntimeError("nmcli failed")

    monkeypatch.setattr("src.core.connection.disconnect_vpn", boom)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    result = ConnectionService(context).disconnect()
    assert result.ok
    context.proxy_state.set_stopped.assert_called_once()


def test_vpn_is_left_alone_when_it_was_not_auto_connected(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system_proxy"
    context.proxy_state.vpn_auto_connected = False
    called = []
    monkeypatch.setattr("src.core.connection.disconnect_vpn", lambda n: called.append(n))
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    ConnectionService(context).disconnect()
    assert called == []


def test_disconnect_restores_the_tun_routes(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = "tun"
    context.proxy_state.started_profile_id = -1
    context.proxy_state.started_mode = "tun"
    restored = []
    monkeypatch.setattr(
        "src.core.connection.restore_tun_routes",
        lambda state: (restored.append(state), (True, ""))[1],
    )
    ConnectionService(context).disconnect()
    assert restored == [None]


def test_reload_without_a_running_proxy_is_refused(tmp_path):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = False
    assert not ConnectionService(context).reload_config().ok


def test_reload_pushes_the_new_config(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.xray_manager.reload_config.return_value = (True, "")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 2})
    assert ConnectionService(context).reload_config().ok
    context.xray_manager.reload_config.assert_called_once()


def test_reload_reports_the_error(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.xray_manager.reload_config.return_value = (False, "bad config")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 2})
    result = ConnectionService(context).reload_config()
    assert not result.ok
    assert result.error == "bad config"


def test_the_monitor_is_started_after_a_successful_connect(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.monitor = MagicMock()
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    ConnectionService(context).connect(1)
    context.monitor.start.assert_called_once()


def test_the_monitor_is_stopped_on_disconnect(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.monitor = MagicMock()
    context.proxy_state.started_profile_id = -1
    context.proxy_state.started_mode = "system_proxy"
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    ConnectionService(context).disconnect()
    context.monitor.stop.assert_called_once()
