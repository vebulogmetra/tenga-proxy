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

    page.update(monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True))
    assert page.get_value("Прокси") == "Работает"


def test_css_class_is_replaced_not_accumulated(page):
    """Two updates in a row must leave exactly one state class on the row."""
    from src.ui.logic.monitoring_view import monitoring_view

    page.update(
        monitoring_view(
            FakeStatus(proxy_ok=False, proxy_error="нет процесса"),
            FakeRouting(),
            is_running=True,
        )
    )
    assert page.get_classes("Прокси") == ["status-error"]

    page.update(monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True))
    assert page.get_classes("Прокси") == ["status-connected"]


def test_rows_are_reused_between_updates(page):
    """Rebuilding the groups would reset the scroll position on every tick."""
    from src.ui.logic.monitoring_view import monitoring_view

    page.update(monitoring_view(FakeStatus(), FakeRouting(), is_running=False))
    first = page.get_row_widget("Прокси")

    page.update(monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True))
    assert page.get_row_widget("Прокси") is first


def test_refresh_button_emits_the_signal(page):
    received: list[bool] = []
    page.connect("refresh-requested", lambda _page: received.append(True))

    page.refresh_button.emit("clicked")

    assert received == [True]


def test_last_check_is_shown(page):
    from src.ui.logic.monitoring_view import monitoring_view

    view = monitoring_view(
        FakeStatus(last_check_time=1_700_000_000.0), FakeRouting(), is_running=False
    )
    page.update(view)

    assert page.get_last_check_text() == view.last_check


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
