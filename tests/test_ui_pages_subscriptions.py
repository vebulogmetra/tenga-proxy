"""Widget tests for the subscriptions page (GTK4)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.gtk


@dataclass
class FakeGroup:
    id: int
    name: str
    is_subscription: bool = True
    subscription_url: str = ""
    last_updated: int = 0


@pytest.fixture
def page(gtk_ready):
    from src.ui.pages.subscriptions import SubscriptionsPage

    return SubscriptionsPage()


@pytest.fixture
def data():
    groups = {
        1: FakeGroup(
            id=1,
            name="Основная",
            subscription_url="https://sub.example/main",
            last_updated=1_700_000_000,
        ),
        2: FakeGroup(id=2, name="Запасная", subscription_url="https://backup.example/list"),
        3: FakeGroup(id=3, name="Локальные", is_subscription=False),
    }
    counts = {1: 120, 2: 0}
    return groups, counts


def test_page_builds(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Widget)


def test_empty_store_shows_the_status_page(page):
    page.set_data({}, {})
    assert page.get_visible_state() == "empty"


def test_rows_match_the_subscription_count(page, data):
    page.set_data(*data)
    assert page.get_visible_state() == "list"
    assert page.get_row_count() == 2


def test_filter_narrows_the_list(page, data):
    page.set_data(*data)
    page.set_query("запас")
    assert page.get_row_count() == 1


def test_filter_without_matches_shows_the_status_page(page, data):
    page.set_data(*data)
    page.set_query("такой подписки нет")
    assert page.get_visible_state() == "empty"


def test_subtitle_carries_the_full_url(page, data):
    long_url = "https://sub.example/" + "x" * 200
    groups, counts = data
    groups[1].subscription_url = long_url
    page.set_data(groups, counts)
    assert long_url in page.get_subtitles()


def test_update_button_emits_the_group_id(page, data):
    received: list[int] = []
    page.connect("subscription-update", lambda _p, group_id: received.append(group_id))

    page.set_data(*data)
    page.click_update_for_test(group_id=2)

    assert received == [2]


def test_row_activation_emits_the_group_id(page, data):
    received: list[int] = []
    page.connect("subscription-activated", lambda _p, group_id: received.append(group_id))

    page.set_data(*data)
    page.activate_row_for_test(group_id=1)

    assert received == [1]


def test_search_bar_can_be_toggled(page):
    page.set_search_enabled(True)
    assert page.search_bar.get_search_mode() is True
    page.set_search_enabled(False)
    assert page.search_bar.get_search_mode() is False


def test_every_row_carries_a_menu_button(page, data):
    page.set_data(*data)

    assert page.get_menu_button_for_test(group_id=1) is not None


def test_the_menu_lists_the_row_actions(page, data):
    page.set_data(*data)

    labels = page.context_menu_labels_for_test(group_id=1)

    assert labels == ["Обновить", "Редактировать", "Удалить"]


def test_the_menu_targets_its_own_row(page, data):
    """У каждой подписки своё меню — иначе действие уйдёт не в ту группу."""
    page.set_data(*data)

    first = page.get_menu_target_for_test(group_id=1)
    second = page.get_menu_target_for_test(group_id=2)

    assert first == 1
    assert second == 2
