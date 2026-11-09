"""Tests for the GTK-free connection service."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from src.core import core_pid
from src.core.connection import ConnectionService
from src.core.http_probe import ProbeEndpoint


@pytest.fixture(autouse=True)
def companion_vpn_capability(monkeypatch):
    monkeypatch.setattr("src.core.connection.companion_vpn_supported", lambda: True)


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
    context.xray_manager.pid = None
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


def test_tun_route_failure_explains_what_is_missing(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = "tun"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr(
        "src.core.connection.apply_tun_routes",
        lambda *_: (False, None, "sudo: a password is required"),
    )
    monkeypatch.setattr("src.core.connection.tun_problems", lambda _xray: ["нет правила sudoers"])

    result = ConnectionService(context).connect(1)

    assert result.error == "нет правила sudoers"


def test_tun_core_failure_explains_what_is_missing(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = "tun"
    context.xray_manager.start.return_value = (False, "xray-core exited with error")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr(
        "src.core.connection.tun_problems", lambda _xray: ["нет cap_net_admin", "нет sudoers"]
    )

    result = ConnectionService(context).connect(1)

    assert result.error == "нет cap_net_admin\nнет sudoers"


def test_system_proxy_failure_is_not_blamed_on_tun(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.start.return_value = (False, "binary not found")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.tun_problems", lambda _xray: ["нет cap_net_admin"])

    assert ConnectionService(context).connect(1).error == "binary not found"


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


# --- служебный inbound проверки соединения ---


def _session_config(*_args):
    return {"inbounds": [], "outbounds": [{"protocol": "vless", "tag": "proxy"}]}


def test_connect_adds_the_health_inbound_and_remembers_its_endpoint(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)

    assert ConnectionService(context).connect(1).ok

    started = context.xray_manager.start.call_args.args[0]
    inbound = started["inbounds"][-1]
    endpoint = context.proxy_state.health_endpoint
    assert isinstance(endpoint, ProbeEndpoint)
    assert inbound["tag"] == "health-in"
    assert inbound["port"] == endpoint.port
    assert inbound["settings"]["accounts"] == [
        {"user": endpoint.credentials.user, "pass": endpoint.credentials.password}
    ]
    assert started["routing"]["rules"][0]["inboundTag"] == ["health-in"]


def test_health_credentials_do_not_reach_the_debug_config(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)

    ConnectionService(context).connect(1)

    written = (tmp_path / "current_config.json").read_text(encoding="utf-8")
    endpoint = context.proxy_state.health_endpoint
    assert "health-in" in written
    assert endpoint.credentials.password not in written
    assert endpoint.credentials.user not in written


def test_failed_start_does_not_publish_a_health_endpoint(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.start.return_value = (False, "binary not found")
    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)

    ConnectionService(context).connect(1)

    assert not isinstance(context.proxy_state.health_endpoint, ProbeEndpoint)


# --- завершение приложения ---


def test_shutdown_waits_for_a_pending_connect_and_stops_the_core(tmp_path, monkeypatch):
    """Выход посреди подключения не должен оставить xray сиротой.

    Иначе ядро держит TUN-интерфейс, и следующий запуск падает с
    «device or resource busy», пока процесс не убьют вручную.
    """
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.is_running = False
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    release = threading.Event()

    def finish_connect():
        release.wait(5)
        context.xray_manager.is_running = True
        context.proxy_state.is_running = True

    pending = threading.Thread(target=finish_connect, daemon=True)
    pending.start()
    threading.Timer(0.1, release.set).start()

    ConnectionService(context).shutdown(pending, timeout=5)

    assert not pending.is_alive()
    context.xray_manager.stop.assert_called_once()


def test_shutdown_stops_a_core_the_state_does_not_know_about(tmp_path, monkeypatch):
    """Ядро запущено, а подключение до `set_running` не дошло."""
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.is_running = True
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)

    ConnectionService(context).shutdown()

    context.xray_manager.stop.assert_called_once()


def test_shutdown_without_a_connection_touches_nothing(tmp_path):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.is_running = False

    ConnectionService(context).shutdown()

    context.xray_manager.stop.assert_not_called()


def test_connection_uses_a_frozen_copy_when_settings_change_during_build(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from src.core.context import AppContext
    from src.db.data_store import DataStore
    from src.fmt.protocols import VLESSBean
    from src.ui.logic.settings_state import runtime_snapshot

    context = AppContext(config_dir=tmp_path, config=DataStore(proxy_mode="system_proxy"))
    profile = context.profiles.add_profile(VLESSBean(server_address="example.com"))
    context._xray_manager = MagicMock()
    context._xray_manager.start.return_value = (True, "")
    context._xray_manager.pid = None
    expected = runtime_snapshot(context.config, profile)
    seen = []

    def build(build_context, _profile):
        context.config.log_level = "debug"
        seen.append(build_context.config.log_level)
        return {"outbounds": [{"protocol": "freedom", "tag": "proxy"}]}

    monkeypatch.setattr("src.core.connection.build_session_config", build)
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_kw: True)
    assert ConnectionService(context).connect(profile.id).ok
    assert seen == ["info"]
    assert context.proxy_state.applied_settings == expected


def test_core_exit_restores_routes_and_stops_the_monitor_but_keeps_vpn(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.config.proxy_mode = "tun"
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "tun"
    context.proxy_state.vpn_auto_connected = True
    context.monitor = MagicMock()
    restored = []
    monkeypatch.setattr(
        "src.core.connection.restore_tun_routes", lambda s: restored.append(s) or (True, "")
    )
    disconnected = []
    monkeypatch.setattr(
        "src.core.connection.disconnect_vpn", lambda name: disconnected.append(name) or True
    )
    service = ConnectionService(context)
    service._tun_route_state = "state"

    profile_id = service.handle_core_exit()

    assert profile_id == 1
    assert restored == ["state"]
    assert disconnected == []
    context.monitor.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()
    # Процесс уже мёртв, но временный конфиг и сокет статистики убирает stop().
    context.xray_manager.stop.assert_called_once()


def test_reconnect_after_core_exit_keeps_ownership_of_the_vpn(tmp_path, monkeypatch):
    """VPN подняли мы: и после перезапуска ядра отключение должно его погасить."""
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.proxy_state.vpn_auto_connected = True
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _name: True)

    assert ConnectionService(context).connect(1).ok

    assert context.proxy_state.vpn_auto_connected is True


def test_started_core_is_remembered_and_forgotten_with_the_session(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.pid = 4242
    context.xray_manager.binary_path = "/opt/xray"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: None)
    service = ConnectionService(context)

    assert service.connect(1).ok
    assert '"pid": 4242' in core_pid.PID_FILE.read_text()

    context.proxy_state.started_mode = "system_proxy"
    service.disconnect()
    assert not core_pid.PID_FILE.exists()


def test_core_without_a_pid_is_not_remembered(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.xray_manager.pid = None
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)

    assert ConnectionService(context).connect(1).ok

    assert not core_pid.PID_FILE.exists()


def test_core_exit_clears_the_system_proxy(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system_proxy"
    cleared = []
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: cleared.append(True))

    ConnectionService(context).handle_core_exit()

    assert cleared == [True]


def test_core_exit_after_a_disconnect_changes_nothing(tmp_path, monkeypatch):
    """Сигнал обогнало отключение: состояние уже убрано, сеанса больше нет."""
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = False
    context.proxy_state.started_mode = "system_proxy"
    cleared = []
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: cleared.append(True))

    assert ConnectionService(context).handle_core_exit() == -1

    assert cleared == []
    context.proxy_state.set_stopped.assert_not_called()


# --- блокировка трафика ---


def _tun_context(tmp_path, monkeypatch, profile=None):
    context = make_context(tmp_path, profile or FakeProfile())
    context.config.proxy_mode = "tun"
    context.proxy_state.started_mode = "tun"
    context.proxy_state.started_profile_id = 1
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.intercepts_dns", lambda _c: False)
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, "state", ""))
    monkeypatch.setattr("src.core.connection.restore_tun_routes", lambda _s: (True, ""))
    return context


def test_tun_connect_blocks_ipv6_before_starting_the_core(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    order = []
    monkeypatch.setattr(
        "src.core.connection.apply_firewall",
        lambda p: order.append((str(p.level), p.tun_name)) or (True, ""),
    )
    context.xray_manager.start.side_effect = lambda _c: order.append("start") or (True, "")

    assert ConnectionService(context).connect(1).ok

    assert order == [("ipv6_only", "xray0"), "start"]


def test_ipv6_block_failure_is_a_warning_not_an_error(tmp_path, monkeypatch):
    context = _tun_context(tmp_path, monkeypatch)
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda _p: (False, "nft not found"))

    result = ConnectionService(context).connect(1)

    assert result.ok
    assert "IPv6" in result.warning
    assert "nft not found" in result.warning


def test_failed_core_start_removes_the_block(tmp_path, monkeypatch, firewall_calls):
    context = _tun_context(tmp_path, monkeypatch)
    context.xray_manager.start.return_value = (False, "bad")
    monkeypatch.setattr("src.core.connection.tun_problems", lambda _b: [])

    assert not ConnectionService(context).connect(1).ok

    assert firewall_calls[-1] == ("remove",)


def test_crashing_core_start_removes_the_block(tmp_path, monkeypatch, firewall_calls):
    context = _tun_context(tmp_path, monkeypatch)
    context.xray_manager.start.side_effect = OSError("boom")

    assert not ConnectionService(context).connect(1).ok

    assert firewall_calls[-1] == ("remove",)


def test_failed_tun_routes_remove_the_block(tmp_path, monkeypatch, firewall_calls):
    context = _tun_context(tmp_path, monkeypatch)
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (False, None, "no"))
    monkeypatch.setattr("src.core.connection.tun_problems", lambda _b: [])

    assert not ConnectionService(context).connect(1).ok

    assert firewall_calls[-1] == ("remove",)


def test_disconnect_removes_the_block_right_after_the_core(tmp_path, monkeypatch):
    """systemd при завершении сеанса ждёт недолго, а `nmcli` может занять 30 с."""
    context = _tun_context(tmp_path, monkeypatch, FakeProfile(vpn_settings=_auto_vpn()))
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: True)
    context.proxy_state.vpn_auto_connected = True
    service = ConnectionService(context)
    assert service.connect(1).ok

    order = []
    context.xray_manager.stop.side_effect = lambda: order.append("stop") or (True, "")
    monkeypatch.setattr(
        "src.core.connection.remove_firewall", lambda: order.append("block") or (True, "")
    )
    monkeypatch.setattr(
        "src.core.connection.restore_tun_routes", lambda _s: order.append("routes") or (True, "")
    )
    monkeypatch.setattr(
        "src.core.connection.disconnect_vpn", lambda _n: order.append("vpn") or True
    )

    service.disconnect()

    assert order == ["stop", "block", "routes", "vpn"]


def _auto_vpn():
    return FakeVpn(enabled=True, auto_connect=True)


def test_core_exit_keeps_the_block(tmp_path, monkeypatch, firewall_calls):
    context = _tun_context(tmp_path, monkeypatch)
    service = ConnectionService(context)
    assert service.connect(1).ok
    context.proxy_state.is_running = True
    firewall_calls.clear()

    assert service.handle_core_exit() == 1

    assert firewall_calls == []


def test_release_after_core_exit_removes_the_block_and_our_vpn(
    tmp_path, monkeypatch, firewall_calls
):
    """Сеанса уже нет, но VPN подняли мы: погасить его при снятии блокировки всё ещё нам."""
    context = _tun_context(tmp_path, monkeypatch, FakeProfile(vpn_settings=_auto_vpn()))
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: True)
    disconnected = []
    monkeypatch.setattr(
        "src.core.connection.disconnect_vpn", lambda n: disconnected.append(n) or True
    )
    context.proxy_state.vpn_auto_connected = True
    service = ConnectionService(context)
    assert service.connect(1).ok
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    assert service.handle_core_exit() == 1
    context.proxy_state.started_profile_id = -1
    firewall_calls.clear()

    assert service.release_block().ok

    assert firewall_calls == [("remove",)]
    assert disconnected == ["my-vpn"]


def test_shutdown_after_a_core_exit_removes_the_block(tmp_path, monkeypatch, firewall_calls):
    """Ядра нет и сеанса нет, а таблица стоит: при выходе её больше некому снять."""
    context = _tun_context(tmp_path, monkeypatch)
    service = ConnectionService(context)
    assert service.connect(1).ok
    context.proxy_state.is_running = True
    assert service.handle_core_exit() == 1
    context.proxy_state.is_running = False
    context.xray_manager.is_running = False
    firewall_calls.clear()

    service.shutdown()

    assert firewall_calls == [("remove",)]


def test_system_proxy_mode_does_not_touch_the_block(tmp_path, monkeypatch, firewall_calls):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.started_mode = "system_proxy"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: None)
    service = ConnectionService(context)

    assert service.connect(1).ok
    service.disconnect()

    assert firewall_calls == []


def test_windows_ignores_saved_companion_vpn_without_system_calls(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.connection.companion_vpn_supported", lambda: False)
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    service = ConnectionService(make_context(tmp_path, profile))
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda *_: pytest.fail("VPN started"))
    monkeypatch.setattr("src.core.connection.disconnect_vpn", lambda *_: pytest.fail("VPN stopped"))
    monkeypatch.setattr(
        "src.core.connection.is_vpn_active", lambda *_: pytest.fail("VPN inspected")
    )
    service._auto_connect_vpn(profile, 1)
    service._auto_disconnect_vpn(1)
    assert service._profile_vpn_name(profile) is None
