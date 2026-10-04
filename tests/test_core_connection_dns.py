"""Подключение в режиме TUN направляет системный DNS в туннель."""

from __future__ import annotations

import pytest

from src.core.connection import ConnectionService
from tests.test_core_connection import FakeProfile, make_context

INTERCEPTING = {"outbounds": [{"tag": "proxy"}, {"tag": "dns-out", "protocol": "dns"}]}
PLAIN = {"outbounds": [{"tag": "proxy"}]}


@pytest.fixture
def steering(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, object(), ""))
    monkeypatch.setattr(
        "src.core.connection.route_system_dns_to_tun",
        lambda tun_name: calls.append(tun_name) or (True, ""),
    )
    return calls


def connect(tmp_path, monkeypatch, config, mode="tun"):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = mode
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: config)
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    return ConnectionService(context).connect(1)


def test_system_dns_is_routed_into_the_tunnel(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, INTERCEPTING).ok
    assert steering == ["xray0"]


def test_config_without_interception_leaves_system_dns_alone(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, PLAIN).ok
    assert steering == []


def test_system_proxy_mode_leaves_system_dns_alone(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, INTERCEPTING, mode="system_proxy").ok
    assert steering == []


def test_failed_steering_does_not_fail_the_connection(tmp_path, monkeypatch):
    """Без него DNS идёт как раньше, мимо туннеля: хуже, но подключение работает."""
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, object(), ""))
    monkeypatch.setattr(
        "src.core.connection.route_system_dns_to_tun", lambda _tun: (False, "access denied")
    )

    assert connect(tmp_path, monkeypatch, INTERCEPTING).ok


@pytest.mark.parametrize(
    ("config", "mode", "reload_ok", "expected"),
    [
        (INTERCEPTING, "tun", True, ["xray0"]),
        (PLAIN, "tun", True, []),
        (INTERCEPTING, "system_proxy", True, []),
        (INTERCEPTING, "tun", False, []),
    ],
)
def test_reload_reapplies_dns_only_after_successful_tun_restart(
    tmp_path, monkeypatch, steering, config, mode, reload_ok, expected
):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = mode
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.xray_manager.reload_config.return_value = (reload_ok, "restart failed")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: config)
    assert ConnectionService(context).reload_config().ok == reload_ok
    assert steering == expected
