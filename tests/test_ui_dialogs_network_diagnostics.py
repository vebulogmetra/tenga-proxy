"""Окно «Диагностика сети» в GTK: рисует представление и зовёт сессию."""

from __future__ import annotations

import json

import pytest

from tests.test_ui_diagnostics_view import dns, full, report, session_with

pytestmark = pytest.mark.gtk


class Loop:
    """Как GLibLoop, но таймер срабатывает сразу по вызову `fire`."""

    def __init__(self):
        self.timers = []

    def dispatch(self, fn, *args):
        fn(*args)

    def schedule(self, _interval_ms, fn):
        self.timers.append(fn)
        return fn

    def cancel(self, handle):
        if handle in self.timers:
            self.timers.remove(handle)


@pytest.fixture
def make(gtk_ready):
    from src.ui.dialogs.network_diagnostics import NetworkDiagnosticsWindow

    windows = []

    def build(session):
        calls = []
        window = NetworkDiagnosticsWindow(session, Loop(), on_recommendation=calls.append)
        window.calls = calls
        windows.append(window)
        return window

    yield build
    for window in windows:
        window.close()


def _walk(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def _texts(window):
    from gi.repository import Adw, Gtk

    out = []
    for item in _walk(window):
        if isinstance(item, Gtk.Label) or (isinstance(item, Gtk.Button) and item.get_label()):
            out.append(item.get_label())
        elif isinstance(item, Adw.PreferencesRow):
            out.append(item.get_title())
    return out


def _button(window, label):
    from gi.repository import Gtk

    for item in _walk(window):
        if isinstance(item, Gtk.Button) and item.get_label() == label:
            return item
    raise AssertionError(f"нет кнопки {label!r}")


def test_idle_window_offers_only_start(make):
    window = make(session_with())
    assert window.get_title() == "Диагностика сети"
    assert window.primary_button.get_label() == "Проверить сеть"
    texts = _texts(window)
    assert "Проверка подключения" in texts
    assert "Скопировать итог" not in texts
    assert "Экспорт отчёта…" not in texts


def test_finished_report_shows_cards_and_actions(make):
    window = make(session_with(full()))
    texts = _texts(window)
    for expected in (
        "Белые списки",
        "Доступ к сервисам",
        "DNS",
        "Технические результаты",
        "Скопировать итог",
        "Экспорт отчёта…",
        "Похоже, оператор включил белые списки",
    ):
        assert expected in texts


def test_detail_rows_are_built_when_expanded(make):
    from gi.repository import Adw

    window = make(session_with(full()))
    expander = next(
        item
        for item in _walk(window)
        if isinstance(item, Adw.ExpanderRow) and item.get_title().startswith("Российские ориентиры")
    )
    assert "ya.ru" not in _texts(window)
    expander.set_expanded(True)
    assert "ya.ru" in _texts(window)


def test_expanded_group_survives_rerender(make):
    from gi.repository import Adw

    session = session_with(full())
    window = make(session)
    next(
        item
        for item in _walk(window)
        if isinstance(item, Adw.ExpanderRow) and item.get_title().startswith("Российские ориентиры")
    ).set_expanded(True)
    session.report = report(allowlist_assessment=full().allowlist_assessment, dns_assessment=dns())
    window._updater._flush()
    assert "ya.ru" in _texts(window)


def test_primary_button_starts_and_stops(make):
    calls = []
    session = session_with()
    session.start = lambda section=None: calls.append(("start", section)) or True
    session.stop = lambda: calls.append(("stop",))
    window = make(session)
    window.primary_button.emit("clicked")
    session.running = True
    window.primary_button.emit("clicked")
    assert calls == [("start", None), ("stop",)]


def test_retry_starts_that_section(make):
    from gi.repository import Gtk

    from src.diag.models import DiagnosticSection

    calls = []
    session = session_with(full())
    session.start = lambda section=None: calls.append(section) or True
    window = make(session)
    retries = [
        item
        for item in _walk(window)
        if isinstance(item, Gtk.Button) and item.get_label() == "Проверить снова"
    ]
    assert len(retries) == 3
    retries[2].emit("clicked")
    assert calls == [DiagnosticSection.DNS]


def test_copy_puts_text_on_clipboard(make):
    window = make(session_with(full()))
    window.on_copy()
    assert window.last_toast_for_test == "Итог скопирован"


def test_save_report_writes_file_and_toasts(make, tmp_path):
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
    from src.diag.models import DiagnosticFinding, EvidenceLevel

    finding = DiagnosticFinding("X", EvidenceLevel.LIKELY, ("network",), ("CHECK_SYSTEM_DNS",))
    window = make(session_with(report(findings=(finding,))))
    _button(window, "Настройки DNS").emit("clicked")
    assert window.calls == ["CHECK_SYSTEM_DNS"]


def test_close_stops_the_session(make):
    session = session_with()
    closed = []
    session.close = lambda: closed.append(1)
    window = make(session)
    window.present()
    window.close()
    assert closed == [1]


def test_monitoring_page_button_requests_diagnostics(gtk_ready):
    from src.ui.pages.monitoring import MonitoringPage

    page = MonitoringPage()
    requested = []
    page.connect("diagnostics-requested", lambda _page: requested.append(1))
    page.diagnostics_button.emit("clicked")
    assert requested == [1]
