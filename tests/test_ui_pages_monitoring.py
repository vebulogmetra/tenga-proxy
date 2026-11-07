"""Widget tests for the monitoring page (GTK4)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

pytestmark = pytest.mark.gtk


@dataclass
class FakeStatus:
    proxy_ok: bool = False
    vpn_ok: bool = True
    last_check_time: float = 0.0
    proxy_error: str = ""
    vpn_error: str = ""


@dataclass
class FakeRouting:
    mode: str = "custom"
    proxy_list: list[str] = field(default_factory=list)
    direct_list: list[str] = field(default_factory=list)
    vpn_list: list[str] = field(default_factory=list)
    bypass_local_networks: bool = False


@pytest.fixture
def page(gtk_ready):
    from src.ui.pages.monitoring import MonitoringPage

    return MonitoringPage()


def test_page_builds(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Widget)


def test_row_count_matches_the_view(page):
    from src.ui.logic.monitoring_view import monitoring_view

    view = monitoring_view(FakeStatus(), FakeRouting(), is_running=False)
    page.update(view)

    assert page.get_row_count() == len(view.connection) + len(view.routing)


def test_update_changes_the_values(page):
    from src.ui.logic.monitoring_view import monitoring_view

    page.update(monitoring_view(FakeStatus(), FakeRouting(), is_running=False))
    assert page.get_value("Прокси") == "Не запущен"

    page.update(
        monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True, checked=True)
    )
    assert page.get_value("Прокси") == "Работает"


def test_css_class_is_replaced_not_accumulated(page):
    """Two updates in a row must leave exactly one state class on the row."""
    from src.ui.logic.monitoring_view import monitoring_view

    page.update(
        monitoring_view(
            FakeStatus(proxy_ok=False, proxy_error="нет процесса"),
            FakeRouting(),
            is_running=True,
            checked=True,
        )
    )
    assert page.get_classes("Прокси") == ["status-error"]

    page.update(
        monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True, checked=True)
    )
    assert page.get_classes("Прокси") == ["status-connected"]


def test_rows_are_reused_between_updates(page):
    """Rebuilding the groups would reset the scroll position on every tick."""
    from src.ui.logic.monitoring_view import monitoring_view

    page.update(monitoring_view(FakeStatus(), FakeRouting(), is_running=False))
    first = page.get_row_widget("Прокси")

    page.update(
        monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True, checked=True)
    )
    assert page.get_row_widget("Прокси") is first


def test_refresh_button_emits_the_signal(page):
    received: list[bool] = []
    page.connect("refresh-requested", lambda _page: received.append(True))

    page.check_button.emit("clicked")

    assert received == [True]


def test_last_check_is_shown(page):
    from src.ui.logic.monitoring_view import monitoring_view

    view = monitoring_view(
        FakeStatus(last_check_time=1_700_000_000.0), FakeRouting(), is_running=False
    )
    page.update(view)

    assert page.get_last_check_text() == view.last_check_line


def test_vpn_rows_of_both_sections_are_independent(gtk_ready):
    """ "VPN" is a row title in both sections; one must not overwrite the other."""
    from src.ui.logic.monitoring_view import monitoring_view
    from src.ui.pages.monitoring import SECTION_CONNECTION, SECTION_ROUTING, MonitoringPage

    page = MonitoringPage()
    view = monitoring_view(
        FakeStatus(proxy_ok=True, vpn_ok=True),
        FakeRouting(mode="custom", vpn_list=["a"]),
        is_running=True,
        vpn_enabled=True,
        vpn_is_up=True,
    )
    page.update(view)

    assert page.get_value("VPN", section=SECTION_CONNECTION) == "Активен"
    assert page.get_value("VPN", section=SECTION_ROUTING) == "активен (1 правил)"


def test_page_layout_matches_qt(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Box)
    assert page.get_group_titles() == ["Состояние соединения", "Маршрутизация", "Журнал"]
    assert page.check_button.get_label() == "Проверить сейчас"
    assert page.diagnostics_button.get_label() == "Диагностика сети…"
    assert page.wrap_check.get_label() == "Перенос строк"
    assert [b.get_label() for b in page.log_buttons] == ["Обновить", "Экспорт…", "Очистить"]


def test_first_row_says_not_checked_until_the_monitor_ran(page):
    from src.ui.logic.monitoring_view import LAST_CHECK_PENDING, NOT_CHECKED, monitoring_view

    page.update(monitoring_view(FakeStatus(), FakeRouting(), is_running=True))
    assert page.get_value("Прокси") == NOT_CHECKED
    assert page.get_last_check_text() == LAST_CHECK_PENDING


def test_diagnostics_button_emits_its_signal(page):
    seen = []
    page.connect("diagnostics-requested", lambda _page: seen.append(True))
    page.diagnostics_button.emit("clicked")
    assert seen == [True]


def test_wrap_toggle_changes_the_text_view(page):
    from gi.repository import Gtk

    assert page.log_view.get_wrap_mode() == Gtk.WrapMode.NONE
    page.wrap_check.set_active(True)
    assert page.log_view.get_wrap_mode() == Gtk.WrapMode.WORD_CHAR
    page.wrap_check.set_active(False)
    assert page.log_view.get_wrap_mode() == Gtk.WrapMode.NONE


def test_log_timer_runs_only_while_active(page, monkeypatch):
    monkeypatch.setattr(page, "refresh_diagnostics", lambda *_a: None)
    assert page.log_timer_running_for_test() is False
    page.set_active(True)
    assert page.log_timer_running_for_test() is True
    page.set_active(True)
    page.set_active(False)
    assert page.log_timer_running_for_test() is False
