"""Окно «Диагностика сети» в Qt: рисует представление и зовёт сессию."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from src.core.context import AppContext
from src.core.main_loop import ImmediateLoop
from src.diag.models import DiagnosticFinding, DiagnosticSection, EvidenceLevel
from src.ui.logic.menus import MAIN_MENU
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.network_diagnostics import NetworkDiagnosticsWindow
from tests.support.qt import process_events
from tests.test_ui_diagnostics_view import dns, full, report, session_with

pytestmark = pytest.mark.qt


@pytest.fixture
def make(qapp):
    windows = []

    def build(session):
        calls = []
        window = NetworkDiagnosticsWindow(session, ImmediateLoop(), on_recommendation=calls.append)
        window.calls = calls
        windows.append(window)
        return window

    yield build
    for window in windows:
        window.close()


def _texts(window):
    out = [label.text() for label in window.findChildren(QLabel)]
    out += [button.text() for button in window.findChildren(QPushButton)]
    out += [button.text() for button in window.findChildren(QToolButton)]
    return out


def _button(window, text):
    return next(b for b in window.findChildren(QPushButton) if b.text() == text)


def test_idle_window_offers_only_start(make):
    window = make(session_with())
    assert window.windowTitle() == "Диагностика сети"
    assert window.primary_button.text() == "Проверить сеть"
    texts = _texts(window)
    assert "Проверка подключения" in texts
    assert "Скопировать итог" not in texts


def test_finished_report_shows_cards_and_actions(make):
    window = make(session_with(full()))
    texts = _texts(window)
    for expected in (
        "Скопировать итог",
        "Экспорт отчёта…",
        "Похоже, оператор включил белые списки",
    ):
        assert expected in texts
    titles = {box.title() for box in window.findChildren(type(window._summary(window.view)))}
    assert {"Белые списки", "Доступ к сервисам", "DNS", "Технические результаты"} <= titles


def test_detail_rows_are_built_when_expanded(make):
    window = make(session_with(full()))
    assert "ya.ru" not in _texts(window)
    header = next(
        b for b in window.findChildren(QToolButton) if b.text().startswith("Российские ориентиры")
    )
    header.setChecked(True)
    assert "ya.ru" in _texts(window)


def test_expanded_group_survives_rerender(make):
    session = session_with(full())
    window = make(session)
    next(
        b for b in window.findChildren(QToolButton) if b.text().startswith("Российские ориентиры")
    ).setChecked(True)
    session.report = report(allowlist_assessment=full().allowlist_assessment, dns_assessment=dns())
    window._updater._flush()
    process_events()
    labels = [label.text() for label in window._scroll.widget().findChildren(QLabel)]
    assert "ya.ru" in labels


def test_primary_button_starts_and_stops(make):
    calls = []
    session = session_with()
    session.start = lambda section=None: calls.append(("start", section)) or True
    session.stop = lambda: calls.append(("stop",))
    window = make(session)
    window.primary_button.click()
    session.running = True
    window.primary_button.click()
    assert calls == [("start", None), ("stop",)]


def test_retry_starts_that_section(make):
    calls = []
    session = session_with(full())
    session.start = lambda section=None: calls.append(section) or True
    window = make(session)
    retries = [b for b in window.findChildren(QPushButton) if b.text() == "Проверить снова"]
    assert len(retries) == 3
    retries[2].click()
    assert calls == [DiagnosticSection.DNS]


def test_copy_puts_text_on_clipboard(make):
    window = make(session_with(full()))
    window.on_copy()
    assert window.last_toast_for_test == "Итог скопирован"
    assert "Диагностика сети · Veblock" in QApplication.clipboard().text()


def test_save_report_writes_file(make, tmp_path):
    window = make(session_with(full()))
    path = tmp_path / "report.json"
    window.save_report(str(path))
    assert window.last_toast_for_test == "Отчёт сохранён"
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 2


def test_save_report_failure_is_shown(make, tmp_path):
    window = make(session_with(full()))
    window.save_report(str(tmp_path / "no" / "dir" / "report.json"))
    assert window.last_toast_for_test == "Не удалось сохранить отчёт. Повторите попытку."


def test_recommendation_button_calls_back(make):
    finding = DiagnosticFinding("X", EvidenceLevel.LIKELY, ("network",), ("CHECK_SYSTEM_DNS",))
    window = make(session_with(report(findings=(finding,))))
    _button(window, "Настройки DNS").click()
    assert window.calls == ["CHECK_SYSTEM_DNS"]


def test_close_stops_the_session(make):
    session = session_with()
    closed = []
    session.close = lambda: closed.append(1)
    window = make(session)
    window.show()
    window.close()
    process_events()
    assert closed == [1]


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    return QtApplication(context, with_tray=False)


def test_action_opens_one_window(app):
    assert "network-diagnostics" in dict(MAIN_MENU)
    app.activate_action("network-diagnostics")
    window = app.diagnostics_window
    assert isinstance(window, NetworkDiagnosticsWindow)
    app.activate_action("network-diagnostics")
    assert app.diagnostics_window is window
    window.close()
    process_events()
    assert app.diagnostics_window is None


def test_action_has_shortcut(app):
    assert app.actions["network-diagnostics"].shortcut().toString() == "Ctrl+D"
