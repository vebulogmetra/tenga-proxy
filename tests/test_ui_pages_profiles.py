"""Widget tests for the profiles page (GTK4)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.gtk


@dataclass
class FakeGroup:
    id: int
    name: str
    is_subscription: bool = False


@dataclass
class FakeBean:
    display_address: str


@dataclass
class FakeProfile:
    id: int
    name: str
    proxy_type: str
    bean: FakeBean
    latency_ms: int = -1


@pytest.fixture
def page(gtk_ready):
    from src.ui.pages.profiles import ProfilesPage

    return ProfilesPage()


@pytest.fixture
def data():
    groups = {
        1: FakeGroup(id=1, name="Работа"),
        2: FakeGroup(id=2, name="Подписка", is_subscription=True),
    }
    profiles = {
        1: [
            FakeProfile(1, "Альфа", "vless", FakeBean("alfa.example:443"), 120),
            FakeProfile(2, "Бета", "trojan", FakeBean("beta.example:8443"), 30),
        ],
        2: [FakeProfile(3, "Гамма", "vmess", FakeBean("gamma.example:80"))],
    }
    return groups, profiles


def test_page_builds(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Widget)


def test_empty_store_shows_the_status_page(page):
    page.set_data({}, {})
    assert page.get_visible_state() == "empty"


def test_non_empty_store_shows_the_list(page, data):
    page.set_data(*data)
    assert page.get_visible_state() == "list"


def test_every_group_becomes_a_root_row(page, data):
    page.set_data(*data)
    assert page.get_root_count() == 2


def test_filter_narrows_the_tree(page, data):
    page.set_data(*data)
    page.set_query("альфа")
    assert page.get_root_count() == 1


def test_filter_without_matches_shows_the_status_page(page, data):
    page.set_data(*data)
    page.set_query("такого профиля нет")
    assert page.get_visible_state() == "empty"


def test_expanding_a_group_reveals_its_profiles(page, data):
    page.set_data(*data)
    page.expand_all()
    # Две группы плюс три профиля.
    assert page.get_visible_row_count() == 5


def test_profile_activated_carries_the_id(page, data):
    received: list[int] = []
    page.connect("profile-activated", lambda _page, profile_id: received.append(profile_id))

    page.set_data(*data)
    page.expand_all()
    page.emit_activation_for_test(profile_id=2)

    assert received == [2]


def test_group_rows_do_not_emit_activation(page, data):
    received: list[int] = []
    page.connect("profile-activated", lambda _page, profile_id: received.append(profile_id))

    page.set_data(*data)
    page.activate_row_for_test(0)

    assert received == []


def test_sorting_by_ping_reorders_profiles(page, data):
    from src.ui.logic.profiles_view import SortKey

    page.set_data(*data)
    page.set_sort(SortKey.PING, ascending=True)
    rows = page.get_profile_titles(group_id=1)
    assert rows == ["Бета", "Альфа"]


def test_active_profile_is_flagged(page, data):
    page.set_active_profile(3)
    page.set_data(*data)
    assert page.get_active_titles() == ["Гамма"]


def test_search_bar_can_be_toggled(page):
    page.set_search_enabled(True)
    assert page.search_bar.get_search_mode() is True
    page.set_search_enabled(False)
    assert page.search_bar.get_search_mode() is False


def test_group_count_is_a_separate_label(gtk_ready, data):
    """The count must survive ellipsization of a long group name."""
    from src.ui.logic.profiles_view import build_profile_rows
    from src.ui.pages.profiles import RowItem

    groups, profiles = data
    groups[1].name = "очень-длинное-имя-группы-" + "х" * 120
    rows = build_profile_rows(groups, profiles)
    group_row = next(row for row in rows if row.group_id == 1)

    item = RowItem(group_row)
    assert item.title == groups[1].name
    assert item.count_text == "2"


def test_profile_rows_carry_no_count(gtk_ready, data):
    from src.ui.logic.profiles_view import build_profile_rows
    from src.ui.pages.profiles import RowItem

    groups, profiles = data
    rows = build_profile_rows(groups, profiles)
    leaf = RowItem(rows[0].children[0])
    assert leaf.count_text == ""
