from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from src.core.context import AppContext
from src.core.monitor import ConnectionMonitor, ConnectionStatus
from src.core.xray_manager import TrafficStats


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
        # Таймеров два: проверка доступности раз в пять секунд и счётчик
        # трафика раз в секунду — растущим байтам десять секунд слишком редко.
        intervals = [call[0][0] for call in mock_timeout_add.call_args_list]
        assert intervals == [5000, 1000]
        assert all(callable(call[0][1]) for call in mock_timeout_add.call_args_list)


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


def test_connection_monitor_check_vpn_uses_active_profile_connection_name(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = True
    context.config.vpn.connection_name = "global-vpn"
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 42

    profile_vpn = SimpleNamespace(enabled=True, connection_name="profile-vpn")
    profile = SimpleNamespace(vpn_settings=profile_vpn)
    context._profiles = MagicMock()
    context._profiles.get_profile.return_value = profile

    monitor = ConnectionMonitor(context)

    with patch("src.sys.vpn.is_vpn_active") as mock_is_active:
        mock_is_active.return_value = True
        ok, error = monitor._check_vpn_status()

        assert ok is True
        assert error == ""
        mock_is_active.assert_called_once_with("profile-vpn")


def test_connection_monitor_should_check_vpn_for_active_profile_when_global_disabled(tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.vpn.enabled = False
    context.config.vpn.connection_name = ""
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 7

    profile_vpn = SimpleNamespace(enabled=True, connection_name="aiso")
    profile = SimpleNamespace(vpn_settings=profile_vpn)
    context._profiles = MagicMock()
    context._profiles.get_profile.return_value = profile

    monitor = ConnectionMonitor(context)

    assert monitor._should_check_vpn() is True


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
    context.config.vpn.connection_name = ""
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = -1

    mock_manager = MagicMock()
    mock_manager.is_running = True
    mock_manager.get_version.return_value = {"version": "1.0.0"}
    context._xray_manager = mock_manager

    monitor = ConnectionMonitor(context)
    callback = Mock()
    monitor.set_on_status_changed(callback)

    # Устанавливаем _timer_id, чтобы _check_connections() не вернул False сразу
    monitor._timer_id = 123

    with (
        patch("src.core.monitor.threading.Thread") as mock_thread,
        patch("gi.repository.GLib.idle_add", side_effect=lambda callback, *args: callback(*args)),
    ):
        mock_thread.return_value.start.side_effect = monitor._do_check_async
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


def test_check_skipped_while_previous_check_running(tmp_path, monkeypatch):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 1

    started: list[object] = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self._target = target
            self._args = args

        def start(self):
            started.append(self._args)

    monkeypatch.setattr("src.core.monitor.threading.Thread", FakeThread)

    assert monitor._check_connections() is True
    assert monitor._check_connections() is True  # второй тик пропускается
    assert len(started) == 1
    assert monitor._check_in_progress is True

    monitor._finish_check(monitor._check_generation)
    assert monitor._check_in_progress is False
    assert monitor._check_connections() is True
    assert len(started) == 2


def test_stop_clears_check_in_progress_flag(tmp_path, monkeypatch):
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 7
    monitor._check_in_progress = True

    monkeypatch.setattr("gi.repository.GLib.source_remove", lambda _id: True)
    monitor.stop()

    assert monitor._check_in_progress is False
    assert monitor._timer_id is None


def test_stop_clears_flag_even_without_an_armed_timer(tmp_path):
    """stop() без таймера тоже обязан снять флаг, иначе тики залипнут навсегда."""
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = None
    monitor._check_in_progress = True

    monitor.stop()

    assert monitor._check_in_progress is False


def test_monitor_recovers_after_stop_without_timer(tmp_path, monkeypatch):
    """После stop() без таймера следующий тик должен запустить проверку."""
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    monitor = ConnectionMonitor(context)
    monitor._check_in_progress = True
    monitor._timer_id = None

    started: list[object] = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self._args = args

        def start(self):
            started.append(self._args)

    monkeypatch.setattr("src.core.monitor.threading.Thread", FakeThread)

    monitor.stop()
    monitor._timer_id = 3
    assert monitor._check_connections() is True
    assert len(started) == 1


def test_stale_check_completion_does_not_unblock_the_current_check(tmp_path, monkeypatch):
    """A check superseded by stop()/start() must not clear the new check's flag."""
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 1

    started: list[object] = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self._args = args

        def start(self):
            started.append(self._args)

    monkeypatch.setattr("src.core.monitor.threading.Thread", FakeThread)
    monkeypatch.setattr("gi.repository.GLib.source_remove", lambda _id: True)

    monitor._check_connections()  # проверка A
    stale_generation = monitor._check_generation
    monitor.stop()
    monitor._timer_id = 2
    monitor._check_connections()  # проверка B
    assert len(started) == 2
    assert monitor._check_in_progress is True

    monitor._finish_check(stale_generation)  # запоздавший колбэк от A
    assert monitor._check_in_progress is True, "устаревший колбэк снял флаг текущей проверки"

    assert monitor._check_connections() is True
    assert len(started) == 2, "лишний параллельный запуск проверки"

    monitor._finish_check(monitor._check_generation)
    assert monitor._check_in_progress is False


def _context_with_traffic(tmp_path, stats):
    """Context whose core reports these counters.

    Менеджер подставляется готовым: ленивое свойство иначе создало бы
    настоящий XrayManager и полезло бы за бинарником.
    """
    context = AppContext(config_dir=tmp_path)
    context._xray_manager = SimpleNamespace(get_traffic=lambda: stats)
    return context


def test_refresh_traffic_writes_the_counters_into_the_state(tmp_path):
    """Опрос кладёт цифры в состояние: карточка читает их оттуда."""
    context = _context_with_traffic(tmp_path, TrafficStats(upload=4096, download=8192))
    context.proxy_state.set_running(profile_id=1)

    ConnectionMonitor(context).refresh_traffic()

    assert context.proxy_state.upload_bytes == 4096
    assert context.proxy_state.download_bytes == 8192


def test_refresh_traffic_notifies_the_listeners(tmp_path):
    """Карточка перерисовывается по уведомлению состояния."""
    context = _context_with_traffic(tmp_path, TrafficStats(upload=10, download=20))
    context.proxy_state.set_running(profile_id=1)
    seen = []
    context.proxy_state.add_listener(lambda _state: seen.append(1))

    ConnectionMonitor(context).refresh_traffic()

    assert seen, "слушателей обязаны были уведомить"


def test_refresh_traffic_stays_quiet_when_nothing_changed(tmp_path):
    """Неизменившиеся цифры не поднимают перерисовку раз в секунду впустую."""
    context = _context_with_traffic(tmp_path, TrafficStats(upload=10, download=20))
    context.proxy_state.set_running(profile_id=1)
    ConnectionMonitor(context).refresh_traffic()

    seen = []
    context.proxy_state.add_listener(lambda _state: seen.append(1))
    ConnectionMonitor(context).refresh_traffic()

    assert not seen


def test_refresh_traffic_skips_a_stopped_core(tmp_path):
    """У остановленного ядра спрашивать нечего: процесса нет."""
    called = []

    context = AppContext(config_dir=tmp_path)
    context._xray_manager = SimpleNamespace(get_traffic=lambda: called.append(1) or TrafficStats())
    context.proxy_state.set_stopped()

    ConnectionMonitor(context).refresh_traffic()

    assert not called


def test_refresh_traffic_survives_a_failing_core(tmp_path):
    """Опрос идёт по таймеру: исключение ядра не вправе его оборвать."""

    def explode():
        raise RuntimeError("ядро отвалилось")

    context = AppContext(config_dir=tmp_path)
    context._xray_manager = SimpleNamespace(get_traffic=explode)
    context.proxy_state.set_running(profile_id=1)

    ConnectionMonitor(context).refresh_traffic()

    assert context.proxy_state.upload_bytes == 0


def test_stop_removes_the_traffic_timer_too(tmp_path):
    """Таймер трафика не должен пережить остановку наблюдения."""
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = 456
    monitor._traffic_timer_id = 789

    removed = []
    mock_glib = MagicMock()
    mock_glib.source_remove = removed.append
    mock_gi_repository = MagicMock()
    mock_gi_repository.GLib = mock_glib

    with patch.dict(
        sys.modules, {"gi.repository": mock_gi_repository, "gi.repository.GLib": mock_glib}
    ):
        monitor.stop()

    assert sorted(removed) == [456, 789]
    assert monitor._traffic_timer_id is None


def test_stop_removes_the_traffic_timer_without_the_main_one(tmp_path):
    """Ранний возврат по пустому основному таймеру не оставляет трафик висеть."""
    context = AppContext(config_dir=tmp_path)
    monitor = ConnectionMonitor(context)
    monitor._timer_id = None
    monitor._traffic_timer_id = 789

    removed = []
    mock_glib = MagicMock()
    mock_glib.source_remove = removed.append
    mock_gi_repository = MagicMock()
    mock_gi_repository.GLib = mock_glib

    with patch.dict(
        sys.modules, {"gi.repository": mock_gi_repository, "gi.repository.GLib": mock_glib}
    ):
        monitor.stop()

    assert removed == [789]
    assert monitor._traffic_timer_id is None
