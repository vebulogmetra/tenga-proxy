"""Небезопасный конфиг не запускается, а причина доходит до пользователя."""

from __future__ import annotations

from src.core.config_builder import UnsafeConfigError
from src.core.connection import ConnectionService
from tests.test_core_connection import FakeProfile, make_context


def refuse(*_args):
    raise UnsafeConfigError(["первый outbound — freedom"])


def test_connect_reports_why_the_config_was_refused(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", refuse)

    result = ConnectionService(context).connect(1)

    assert not result.ok
    assert result.error == "Конфигурация отклонена: первый outbound — freedom"
    context.xray_manager.start.assert_not_called()


def test_reload_reports_why_the_config_was_refused(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    monkeypatch.setattr("src.core.connection.build_session_config", refuse)

    result = ConnectionService(context).reload_config()

    assert not result.ok
    assert "Конфигурация отклонена" in result.error
    context.xray_manager.reload_config.assert_not_called()
