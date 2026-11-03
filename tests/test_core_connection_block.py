"""Блокировка трафика в жизненном цикле подключения: уровень `full`, VPN, окно DNS."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from src.core import core_pid
from src.core.connection import (
    DNS_UNPROTECTED,
    KILL_SWITCH_NEEDS_DNS,
    ConnectionService,
)
from src.sys.firewall_policy import Level


@dataclass
class FakeVpn:
    enabled: bool = True
    connection_name: str = "corp"
    auto_connect: bool = True


@dataclass
class FakeProfile:
    id: int = 1
    name: str = "P"
    vpn_settings: FakeVpn | None = None
    routing_settings: object | None = None
    bean: object = field(default_factory=lambda: MagicMock(server_address="1.2.3.4"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Сеанс TUN с включённой блокировкой, перехватом DNS и resolved."""
    context = MagicMock()
    profiles = {1: FakeProfile(id=1), 2: FakeProfile(id=2)}
    context.config_dir = tmp_path
    context.profiles.get_profile.side_effect = profiles.get
    context.xray_manager.start.return_value = (True, "")
    context.xray_manager.stop.return_value = (True, "")
    context.xray_manager.pid = None
    context.config.proxy_mode = "tun"
    context.config.tun_name = "xray0"
    context.config.tun_kill_switch = True
    context.proxy_state.is_running = False
    context.proxy_state.started_mode = "tun"
    context.proxy_state.started_profile_id = -1
    context.proxy_state.traffic_blocked = False
    context.proxy_state.dns_unprotected = False
    context.proxy_state.vpn_auto_connected = False
    context.monitor = None

    def set_running(profile_id, mode="tun"):
        context.proxy_state.is_running = True
        context.proxy_state.started_profile_id = profile_id
        context.proxy_state.started_mode = mode

    def set_stopped():
        context.proxy_state.is_running = False
        context.proxy_state.started_profile_id = -1

    context.proxy_state.set_running.side_effect = set_running
    context.proxy_state.set_stopped.side_effect = set_stopped

    for name, value in {
        "build_session_config": lambda *_: {"a": 1},
        "intercepts_dns": lambda _c: True,
        "apply_tun_routes": lambda *_: (True, "state", ""),
        "restore_tun_routes": lambda _s: (True, ""),
        "route_system_dns_to_tun": lambda _t: (True, ""),
        "is_vpn_active": lambda _n: True,
        "connect_vpn": lambda _n: True,
        "disconnect_vpn": lambda _n: True,
        "vpn_connection_type": lambda _n: "vpn",
        "vpn_server_addresses": lambda _n: ("203.0.113.5",),
        "vpn_tunnel_interface": lambda _n: "tun0",
    }.items():
        monkeypatch.setattr(f"src.core.connection.{name}", value)

    return context, profiles, ConnectionService(context)


def policies(firewall_calls):
    return [call[1] for call in firewall_calls if call[0] == "apply"]


def removed(firewall_calls) -> bool:
    return ("remove",) in firewall_calls


# --- первое подключение ---


def test_full_block_goes_up_before_the_core_and_dns_closes_after_it(world, firewall_calls):
    context, _, service = world
    order = []
    context.xray_manager.start.side_effect = lambda _c: order.append(len(firewall_calls)) or (
        True,
        "",
    )

    assert service.connect(1).ok

    first, last = policies(firewall_calls)
    assert first.level == Level.FULL
    assert first.dns_closed is False
    assert last.dns_closed is True
    assert order == [1]


def test_dns_closes_only_after_resolved_looks_into_the_tunnel(world, firewall_calls, monkeypatch):
    _, _, service = world
    seen = []

    def route(_tun):
        seen.append(policies(firewall_calls)[-1].dns_closed)
        return True, ""

    monkeypatch.setattr("src.core.connection.route_system_dns_to_tun", route)

    assert service.connect(1).ok

    assert seen == [False]
    assert policies(firewall_calls)[-1].dns_closed is True


def test_without_resolved_dns_stays_open_and_the_user_is_told(world, firewall_calls, monkeypatch):
    context, _, service = world
    monkeypatch.setattr("src.core.connection.route_system_dns_to_tun", lambda _t: (False, "no"))

    result = service.connect(1)

    assert result.ok
    assert result.warning == DNS_UNPROTECTED
    assert context.proxy_state.dns_unprotected is True
    assert all(not policy.dns_closed for policy in policies(firewall_calls))


def _network_uses_dns(monkeypatch, *servers):
    monkeypatch.setattr("src.core.connection.get_default_interface", lambda **_k: "eth0")
    monkeypatch.setattr("src.core.connection.system_dns_servers", lambda _iface: list(servers))


def test_window_opens_for_the_dns_of_the_network(world, firewall_calls, monkeypatch):
    """Имя сервера разрешает DNS сети, а публичный адрес не попадает в локальные сети."""
    _, _, service = world
    _network_uses_dns(monkeypatch, "8.8.8.8")

    assert service.connect(1).ok

    first, last = policies(firewall_calls)[0], policies(firewall_calls)[-1]
    assert first.helper_args()[4:] == ["open", "8.8.8.8"]
    assert last.helper_args()[4:] == ["closed"]


def test_without_a_physical_interface_the_window_names_no_servers(world, firewall_calls):
    _, _, service = world

    assert service.connect(1).ok

    assert policies(firewall_calls)[0].helper_args()[4:] == ["open"]


def test_switching_opens_the_window_for_the_current_network(world, firewall_calls, monkeypatch):
    """После смены сети DNS другой: адреса прошлого сеанса не годятся."""
    _, _, service = world
    _network_uses_dns(monkeypatch, "8.8.8.8")
    assert service.connect(1).ok
    _network_uses_dns(monkeypatch, "1.0.0.1")
    seen = []
    monkeypatch.setattr(
        "src.core.connection.apply_tun_routes",
        lambda *_: (seen.append(policies(firewall_calls)[-1].helper_args()), (True, "s", ""))[1],
    )

    assert service.connect(2).ok

    assert seen[0][4:] == ["open", "1.0.0.1"]


def test_failing_to_close_dns_is_a_warning(world, monkeypatch):
    _, _, service = world
    answers = iter([(True, ""), (False, "nft died")])
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda _p: next(answers))

    result = service.connect(1)

    assert result.ok
    assert result.warning == DNS_UNPROTECTED


def test_full_block_needs_dns_interception(world, firewall_calls, monkeypatch):
    context, _, service = world
    monkeypatch.setattr("src.core.connection.intercepts_dns", lambda _c: False)

    result = service.connect(1)

    assert not result.ok
    assert result.error == KILL_SWITCH_NEEDS_DNS
    assert firewall_calls == []
    context.xray_manager.start.assert_not_called()


def test_full_block_failure_cancels_the_connection(world, monkeypatch):
    context, _, service = world
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda _p: (False, "nft not found"))

    result = service.connect(1)

    assert not result.ok
    assert "nft not found" in result.error
    context.xray_manager.start.assert_not_called()


@pytest.mark.parametrize("step", ["start", "start-raises", "routes", "build"])
def test_failed_first_connection_opens_the_traffic(world, firewall_calls, monkeypatch, step):
    context, _, service = world
    if step == "start":
        context.xray_manager.start.return_value = (False, "bad")
    elif step == "start-raises":
        context.xray_manager.start.side_effect = OSError("boom")
    elif step == "routes":
        monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (False, None, "no"))
    else:
        monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: None)

    assert not service.connect(1).ok

    assert context.proxy_state.traffic_blocked is False
    if step != "build":
        assert removed(firewall_calls)


# --- VPN ---


def test_vpn_tunnel_and_server_are_in_the_rules(world, firewall_calls):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()

    assert service.connect(1).ok

    policy = policies(firewall_calls)[-1]
    assert policy.vpn_interface == "tun0"
    assert policy.vpn_addresses == ("203.0.113.5",)


@pytest.mark.parametrize("kind", ["wireguard", "tun"])
def test_unsupported_vpn_types_are_refused(world, monkeypatch, kind):
    context, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.vpn_connection_type", lambda _n: kind)

    result = service.connect(1)

    assert not result.ok
    assert "WireGuard" in result.error
    context.xray_manager.start.assert_not_called()


def test_vpn_without_a_known_address_is_refused(world, monkeypatch):
    context, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.vpn_server_addresses", lambda _n: ())

    result = service.connect(1)

    assert not result.ok
    assert "corp" in result.error
    context.xray_manager.start.assert_not_called()


def test_vpn_without_a_known_interface_is_refused(world, monkeypatch):
    context, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.vpn_tunnel_interface", lambda _n: None)

    result = service.connect(1)

    assert not result.ok
    assert "интерфейс" in result.error
    context.xray_manager.start.assert_not_called()


def test_vpn_that_did_not_come_up_is_left_out_of_the_rules(world, firewall_calls, monkeypatch):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: False)
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda _n: False)

    assert service.connect(1).ok

    policy = policies(firewall_calls)[-1]
    assert policy.vpn_interface is None
    assert policy.vpn_addresses == ()


def test_disabled_vpn_is_not_asked_about(world, firewall_calls, monkeypatch):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn(enabled=False)

    def boom(_name):
        raise AssertionError("не должно вызываться")

    monkeypatch.setattr("src.core.connection.vpn_connection_type", boom)

    assert service.connect(1).ok


def test_vpn_of_a_session_without_the_setting_is_not_refused(world, monkeypatch):
    """WireGuard работает, пока настройка выключена: уровень ipv6_only ему не мешает."""
    context, profiles, service = world
    context.config.tun_kill_switch = False
    profiles[1].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.vpn_connection_type", lambda _n: "wireguard")

    assert service.connect(1).ok


# --- смена сервера ---


def test_switching_servers_never_removes_the_block(world, firewall_calls):
    _, _, service = world
    assert service.connect(1).ok
    firewall_calls.clear()

    assert service.connect(2).ok

    assert not removed(firewall_calls)
    assert policies(firewall_calls)[-1].dns_closed is True


def test_switching_opens_dns_before_anything_resolves_names(world, firewall_calls, monkeypatch):
    _, _, service = world
    assert service.connect(1).ok
    seen = []
    monkeypatch.setattr(
        "src.core.connection.apply_tun_routes",
        lambda *_: (seen.append(policies(firewall_calls)[-1].dns_closed), (True, "state", ""))[1],
    )

    assert service.connect(2).ok

    assert seen == [False]


def test_switching_keeps_the_same_vpn_up(world, monkeypatch):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    profiles[2].vpn_settings = FakeVpn()
    world[0].proxy_state.vpn_auto_connected = True
    disconnected = []
    monkeypatch.setattr(
        "src.core.connection.disconnect_vpn", lambda n: disconnected.append(n) or True
    )
    assert service.connect(1).ok

    assert service.connect(2).ok

    assert disconnected == []


def test_switching_to_another_vpn_drops_the_one_we_raised(world, monkeypatch):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn(connection_name="old")
    profiles[2].vpn_settings = FakeVpn(connection_name="new")
    world[0].proxy_state.vpn_auto_connected = True
    disconnected = []
    monkeypatch.setattr(
        "src.core.connection.disconnect_vpn", lambda n: disconnected.append(n) or True
    )
    assert service.connect(1).ok

    assert service.connect(2).ok

    assert disconnected == ["old"]


def test_new_vpn_server_is_opened_before_the_vpn_is_raised(world, firewall_calls, monkeypatch):
    """Иначе таблица прошлого сеанса закрыла бы подключение к новому VPN."""
    _, profiles, service = world
    assert service.connect(1).ok
    profiles[2].vpn_settings = FakeVpn()
    seen = []

    def connect_vpn(_name):
        seen.append(policies(firewall_calls)[-1].vpn_addresses)
        return True

    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: bool(seen))
    monkeypatch.setattr("src.core.connection.connect_vpn", connect_vpn)

    assert service.connect(2).ok

    assert seen == [("203.0.113.5",)]


@pytest.mark.parametrize("step", ["start", "routes", "build"])
def test_failed_switch_keeps_the_traffic_closed(world, firewall_calls, monkeypatch, step):
    context, _, service = world
    assert service.connect(1).ok
    firewall_calls.clear()
    if step == "start":
        context.xray_manager.start.return_value = (False, "bad")
    elif step == "routes":
        monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (False, None, "no"))
    else:
        monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: None)

    assert not service.connect(2).ok

    assert not removed(firewall_calls)
    assert context.proxy_state.traffic_blocked is True
    assert context.proxy_state.blocked_profile_id == 2
    assert policies(firewall_calls)[-1].dns_closed is True


def test_refused_switch_keeps_the_traffic_closed(world, firewall_calls, monkeypatch):
    context, profiles, service = world
    assert service.connect(1).ok
    firewall_calls.clear()
    profiles[2].vpn_settings = FakeVpn()
    monkeypatch.setattr("src.core.connection.vpn_connection_type", lambda _n: "wireguard")

    assert not service.connect(2).ok

    assert not removed(firewall_calls)
    assert context.proxy_state.traffic_blocked is True


def test_turning_the_setting_off_downgrades_the_block_atomically(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    firewall_calls.clear()
    context.config.tun_kill_switch = False

    assert service.connect(1).ok

    assert not removed(firewall_calls)
    assert policies(firewall_calls)[-1].level == Level.IPV6_ONLY


def test_failed_switch_after_turning_the_setting_off_opens_the_traffic(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    context.config.tun_kill_switch = False
    context.xray_manager.start.return_value = (False, "bad")

    assert not service.connect(2).ok

    assert removed(firewall_calls)
    assert context.proxy_state.traffic_blocked is False


def test_leaving_tun_for_the_system_proxy_removes_the_table(world, firewall_calls, monkeypatch):
    context, _, service = world
    assert service.connect(1).ok
    context.config.proxy_mode = "system_proxy"
    context.config.inbound_socks_port = 2080
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    firewall_calls.clear()

    assert service.connect(1).ok

    assert removed(firewall_calls)


def test_missing_profile_does_not_tear_the_session_down(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    context.xray_manager.stop.reset_mock()
    firewall_calls.clear()

    assert not service.connect(7).ok

    context.xray_manager.stop.assert_not_called()
    assert firewall_calls == []


# --- падение ядра и снятие ---


def test_core_exit_with_the_setting_marks_the_traffic_blocked(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    firewall_calls.clear()

    assert service.handle_core_exit() == 1

    assert firewall_calls == []
    assert context.proxy_state.traffic_blocked is True
    assert context.proxy_state.blocked_profile_id == 1


def test_core_exit_without_the_setting_blocks_nothing(world):
    context, _, service = world
    context.config.tun_kill_switch = False
    assert service.connect(1).ok

    service.handle_core_exit()

    assert context.proxy_state.traffic_blocked is False


def test_reconnect_after_a_core_exit_clears_the_blocked_state(world):
    context, _, service = world
    assert service.connect(1).ok
    service.handle_core_exit()

    assert service.connect(1).ok

    assert context.proxy_state.traffic_blocked is False


def test_failed_restart_after_a_core_exit_stays_blocked(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    service.handle_core_exit()
    context.xray_manager.start.return_value = (False, "bad")
    firewall_calls.clear()

    assert not service.connect(1).ok

    assert not removed(firewall_calls)
    assert context.proxy_state.traffic_blocked is True


def test_release_opens_the_traffic(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    service.handle_core_exit()
    firewall_calls.clear()

    assert service.release_block().ok

    assert firewall_calls == [("remove",)]
    assert context.proxy_state.traffic_blocked is False
    assert context.proxy_state.blocked_profile_id == -1


def test_disconnect_clears_the_blocked_state(world, firewall_calls):
    context, _, service = world
    assert service.connect(1).ok
    context.proxy_state.traffic_blocked = True

    service.disconnect()

    assert removed(firewall_calls)
    assert context.proxy_state.traffic_blocked is False


# --- метка для следующего запуска ---


def test_marker_lives_only_while_the_full_block_stands(world):
    _, _, service = world

    assert service.connect(1).ok
    assert core_pid.BLOCK_FILE.exists()

    service.disconnect()
    assert not core_pid.BLOCK_FILE.exists()


def test_ipv6_only_leaves_no_marker(world):
    context, _, service = world
    context.config.tun_kill_switch = False

    assert service.connect(1).ok

    assert not core_pid.BLOCK_FILE.exists()


def test_downgrade_drops_the_marker(world):
    context, _, service = world
    assert service.connect(1).ok
    context.config.tun_kill_switch = False

    assert service.connect(1).ok

    assert not core_pid.BLOCK_FILE.exists()


# --- интерфейс VPN ---


def _session_with_vpn(world):
    _, profiles, service = world
    profiles[1].vpn_settings = FakeVpn()
    assert service.connect(1).ok
    return service


def test_vpn_is_watched_only_while_its_interface_is_open(world):
    _, _, service = world
    assert service.watched_vpn() is None
    assert service.connect(2).ok
    assert service.watched_vpn() is None, "Сеанс без VPN"

    assert _session_with_vpn(world).watched_vpn() == "corp"
    service.disconnect()
    assert service.watched_vpn() is None


def test_table_follows_the_vpn_to_a_new_interface(world, firewall_calls):
    service = _session_with_vpn(world)
    before = policies(firewall_calls)[-1]

    assert service.follow_vpn_interface("corp", "tun1") is True

    after = policies(firewall_calls)[-1]
    assert after.vpn_interface == "tun1"
    assert after.vpn_addresses == before.vpn_addresses
    assert after.dns_closed is before.dns_closed


def test_same_interface_does_not_touch_the_table(world, firewall_calls):
    service = _session_with_vpn(world)
    current = policies(firewall_calls)[-1].vpn_interface
    count = len(firewall_calls)

    assert service.follow_vpn_interface("corp", current) is False
    assert len(firewall_calls) == count


def test_late_answer_about_another_vpn_is_ignored(world, firewall_calls):
    service = _session_with_vpn(world)
    count = len(firewall_calls)

    assert service.follow_vpn_interface("old", "tun7") is False
    assert len(firewall_calls) == count


def test_refused_table_change_keeps_watching_the_old_interface(world, firewall_calls, monkeypatch):
    service = _session_with_vpn(world)
    old = policies(firewall_calls)[-1].vpn_interface
    monkeypatch.setattr("src.core.connection.apply_firewall", lambda _p: (False, "nft failed"))

    assert service.follow_vpn_interface("corp", "tun1") is False

    monkeypatch.setattr("src.core.connection.apply_firewall", lambda _p: (True, ""))
    assert service.follow_vpn_interface("corp", old) is False
    assert service.follow_vpn_interface("corp", "tun1") is True


def test_table_follows_the_vpn_under_the_block_too(world, firewall_calls):
    context, _, _ = world
    service = _session_with_vpn(world)
    service.handle_core_exit()
    assert context.proxy_state.traffic_blocked is True

    assert service.follow_vpn_interface("corp", "tun1") is True
    assert policies(firewall_calls)[-1].vpn_interface == "tun1"
