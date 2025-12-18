from __future__ import annotations

import sys
from unittest.mock import MagicMock, Mock, patch

from src.core.context import AppContext
from src.core.monitor import ConnectionMonitor, ConnectionStatus


def test_connection_status_defaults():
    status = ConnectionStatus()
    assert status.proxy_ok is False
    assert status.vpn_ok is False
    assert status.last_check_time == 0.0
    assert status.proxy_error == ""
    assert status.vpn_error == ""


def test_connection_status_initialization():
    status = ConnectionStatus(
        proxy_ok=True,
        vpn_ok=True,
        last_check_time=123.45,
        proxy_error="",
        vpn_error="",
    )
    assert status.proxy_ok is True
    assert status.vpn_ok is True
    assert status.last_check_time == 123.45


def test_connection_monitor_initialization(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    assert monitor._context is context
    assert monitor._timer_id is None
    assert isinstance(monitor._status, ConnectionStatus)
    assert isinstance(monitor._previous_status, ConnectionStatus)
    assert monitor._on_status_changed is None


def test_connection_monitor_set_callback(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    callback = Mock()
    monitor.set_on_status_changed(callback)

    assert monitor._on_status_changed is callback


def test_connection_monitor_start_disabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = False
    monitor = ConnectionMonitor(context)

    monitor.start()

    assert monitor._timer_id is None


def test_connection_monitor_start_enabled(tmp_path, monkeypatch):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    context.config.monitoring.check_interval_seconds = 5

    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    mock_timeout_add = Mock(return_value=123)
    mock_glib = MagicMock()
    mock_glib.timeout_add = mock_timeout_add

    mock_gi_repository = MagicMock()
    mock_gi_repository.GLib = mock_glib

    with patch.dict(
        sys.modules, {"gi.repository": mock_gi_repository, "gi.repository.GLib": mock_glib}
    ):
        monitor = ConnectionMonitor(context)
        monitor.start()

        assert monitor._timer_id == 123
        mock_timeout_add.assert_called_once()
        call_args = mock_timeout_add.call_args
        assert call_args[0][0] == 5000
        assert callable(call_args[0][1])


def test_connection_monitor_stop(tmp_path, monkeypatch):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 456

    mock_source_remove = Mock()
    mock_glib = MagicMock()
    mock_glib.source_remove = mock_source_remove

    mock_gi_repository = MagicMock()
    mock_gi_repository.GLib = mock_glib

    with patch.dict(
        sys.modules, {"gi.repository": mock_gi_repository, "gi.repository.GLib": mock_glib}
    ):
        monitor.stop()

        assert monitor._timer_id is None
        mock_source_remove.assert_called_once_with(456)
        assert monitor._status.proxy_ok is False
        assert monitor._status.vpn_ok is False


def test_connection_monitor_check_proxy_not_running(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.proxy_state.is_running = False
    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_proxy_status()

    assert ok is False
    assert "не запущен" in error


def test_connection_monitor_check_proxy_clash_api_fails(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = None
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_proxy_status()

    assert ok is False
    assert "Clash API" in error


def test_connection_monitor_check_proxy_clash_api_exception(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.side_effect = Exception("Connection refused")
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_proxy_status()

    assert ok is False
    assert "Clash API" in error


def test_connection_monitor_check_proxy_success(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_proxy_status()

    assert ok is True
    assert error == ""


def test_connection_monitor_check_vpn_not_enabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = False
    context.config.vpn.connection_name = ""
    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_vpn_status()

    assert ok is True
    assert error == ""


def test_connection_monitor_check_vpn_no_connection_name(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = True
    context.config.vpn.connection_name = ""
    monitor = ConnectionMonitor(context)

    ok, error = monitor._check_vpn_status()

    assert ok is True
    assert error == ""


def test_connection_monitor_check_vpn_active(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = True
    context.config.vpn.connection_name = "my-vpn"

    monitor = ConnectionMonitor(context)

    with patch("src.sys.vpn.is_vpn_active") as mock_is_active:
        mock_is_active.return_value = True
        ok, error = monitor._check_vpn_status()

        assert ok is True
        assert error == ""
        mock_is_active.assert_called_once_with("my-vpn")


def test_connection_monitor_check_vpn_inactive(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = True
    context.config.vpn.connection_name = "my-vpn"

    monitor = ConnectionMonitor(context)

    with patch("src.sys.vpn.is_vpn_active") as mock_is_active:
        mock_is_active.return_value = False
        ok, error = monitor._check_vpn_status()

        assert ok is False
        assert "не активен" in error
        mock_is_active.assert_called_once_with("my-vpn")


def test_connection_monitor_check_vpn_exception(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = True
    context.config.vpn.connection_name = "my-vpn"

    monitor = ConnectionMonitor(context)

    with patch("src.sys.vpn.is_vpn_active") as mock_is_active:
        mock_is_active.side_effect = Exception("nmcli error")
        ok, error = monitor._check_vpn_status()

        assert ok is False
        assert "Ошибка проверки VPN" in error
        mock_is_active.assert_called_once_with("my-vpn")


def test_connection_monitor_status_changed(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    monitor._status = ConnectionStatus(proxy_ok=True, vpn_ok=True)
    monitor._previous_status = ConnectionStatus(proxy_ok=True, vpn_ok=True)
    assert monitor._status_changed() is False

    monitor._status = ConnectionStatus(proxy_ok=False, vpn_ok=True)
    assert monitor._status_changed() is True

    monitor._previous_status = ConnectionStatus(proxy_ok=False, vpn_ok=True)
    monitor._status = ConnectionStatus(proxy_ok=False, vpn_ok=False)
    assert monitor._status_changed() is True


def test_connection_monitor_notify_status_changed(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    callback = Mock()
    monitor.set_on_status_changed(callback)

    previous = ConnectionStatus(proxy_ok=False)
    current = ConnectionStatus(proxy_ok=True)
    monitor._previous_status = previous
    monitor._status = current

    monitor._notify_status_changed()

    callback.assert_called_once_with(previous, current)


def test_connection_monitor_notify_no_callback(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    monitor._notify_status_changed()


def test_connection_monitor_check_connections_disabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = False
    monitor = ConnectionMonitor(context)

    result = monitor._check_connections()

    assert result is False


def test_connection_monitor_check_connections_enabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    context.config.vpn.enabled = False
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)
    callback = Mock()
    monitor.set_on_status_changed(callback)

    # Устанавливаем _timer_id, чтобы _check_connections() не вернул False сразу
    monitor._timer_id = 123

    result = monitor._check_connections()

    assert result is True
    assert monitor._status.proxy_ok is True
    assert monitor._status.vpn_ok is True
    assert monitor._status.last_check_time > 0
    callback.assert_called_once()


def test_connection_monitor_check_now_disabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = False
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)
    callback = Mock()
    monitor.set_on_status_changed(callback)

    monitor.check_now()

    assert context.config.monitoring.enabled is False
    callback.assert_called()


def test_connection_monitor_check_now_enabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    context.proxy_state.is_running = True

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)
    callback = Mock()
    monitor.set_on_status_changed(callback)

    monitor.check_now()

    callback.assert_called()


def test_connection_monitor_get_status(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)

    monitor._status = ConnectionStatus(proxy_ok=True, vpn_ok=True)

    status = monitor.status
    assert status.proxy_ok is True
    assert status.vpn_ok is True

    status2 = monitor.get_status()
    assert status2 is status


def test_connection_monitor_start_already_started(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 999

    monitor.start()

    assert monitor._timer_id == 999


def test_connection_monitor_stop_not_started(tmp_path):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = None

    monitor.stop()

    assert monitor._timer_id is None
