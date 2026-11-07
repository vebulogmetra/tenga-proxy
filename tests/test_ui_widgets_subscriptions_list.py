"""Widget tests for the subscription list of the settings dialog (GTK4)."""

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
    sub_user_info: str = ""
    sub_announce: str = ""
    sub_support_url: str = ""
    sub_web_page_url: str = ""
    sub_empty: bool = False
    sub_via_fallback: bool = False


@pytest.fixture
def page(gtk_ready):
    from src.ui.widgets.subscriptions_list import SubscriptionsList

    return SubscriptionsList()


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


def test_empty_store_shows_the_empty_row(page):
    page.set_data({}, {})
    assert page.get_visible_state() == "empty"
    assert page.get_empty_text() == "Подписок нет. Добавьте ссылку от провайдера."


def test_rows_match_the_subscription_count(page, data):
    page.set_data(*data)
    assert page.get_visible_state() == "list"
    assert page.get_row_count() == 2


def test_subtitle_carries_the_full_url(page, data):
    long_url = "https://sub.example/" + "x" * 200
    groups, counts = data
    groups[1].subscription_url = long_url
    page.set_data(groups, counts)
    assert long_url in page.get_subtitles()


def test_an_address_with_an_ampersand_is_still_shown(page, data):
    """Адрес с query-параметрами должен отображаться как обычный текст."""
    url = "https://sub.example/list?token=abc&client=tenga"
    groups, counts = data
    groups[1].subscription_url = url
    page.set_data(groups, counts)
    assert url in page.get_subtitles()


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


# --- метаданные провайдера ---

GIB = 1024**3


def test_a_row_without_metadata_has_no_extra_widgets(page, data):
    page.set_data(*data)

    assert page.get_details_for_test(group_id=1) == ""
    assert page.get_announce_for_test(group_id=1) == ""


def test_usage_and_expiry_are_shown_in_the_row(page, data):
    groups, counts = data
    groups[1].sub_user_info = f"upload=0; download={GIB}; total={2 * GIB}; expire=4102444800"
    page.set_data(groups, counts)

    details = page.get_details_for_test(group_id=1)

    assert "1.00 GB из 2.00 GB" in details
    assert "до " in details
    assert not page.is_expired_for_test(group_id=1)


def test_an_expired_subscription_is_highlighted(page, data):
    groups, counts = data
    groups[1].sub_user_info = "upload=0; download=0; total=0; expire=1000000000"
    page.set_data(groups, counts)

    assert "истекла" in page.get_details_for_test(group_id=1)
    assert page.is_expired_for_test(group_id=1)


def test_an_empty_subscription_is_marked_in_its_row(page, data):
    groups, counts = data
    groups[1].sub_empty = True
    page.set_data(groups, counts)

    assert page.is_empty_notice_shown_for_test(group_id=1)
    assert not page.is_empty_notice_shown_for_test(group_id=2)


def test_the_announce_is_available_from_the_row(page, data):
    groups, counts = data
    groups[1].sub_announce = "Техработы <b>до</b> 12:00 & позже"
    page.set_data(groups, counts)

    assert page.get_announce_for_test(group_id=1) == "Техработы <b>до</b> 12:00 & позже"
    assert page.get_announce_for_test(group_id=2) == ""


def test_provider_links_extend_the_menu(page, data):
    groups, counts = data
    groups[1].sub_web_page_url = "https://provider.example/account"
    groups[1].sub_support_url = "https://t.me/provider"
    page.set_data(groups, counts)

    assert page.context_menu_labels_for_test(group_id=1) == [
        "Обновить",
        "Редактировать",
        "Страница подписки",
        "Поддержка",
        "Удалить",
    ]
    assert page.context_menu_labels_for_test(group_id=2) == ["Обновить", "Редактировать", "Удалить"]


def test_an_update_through_the_fallback_is_marked_in_its_row(page, data):
    groups, counts = data
    groups[1].sub_via_fallback = True
    page.set_data(groups, counts)

    assert page.is_via_fallback_shown_for_test(group_id=1)
    assert not page.is_via_fallback_shown_for_test(group_id=2)


def test_update_button_targets_its_row(page, data):
    page.set_data(*data)
    button = page.get_update_button_for_test(group_id=2)
    assert button.get_action_name() == "win.update-subscription"
    assert button.get_action_target_value().get_int32() == 2


def test_activation_selects_the_row_and_retargets_the_buttons(page, data):
    page.set_data(*data)
    labels = [b.get_label() for b in page.buttons]
    assert labels == ["Добавить…", "Обновить", "Изменить…", "Удалить"]
    assert page.buttons[0].get_action_name() == "app.add-subscription"

    page.activate_row_for_test(group_id=2)
    assert page.get_selected() == 2
    assert page.is_selected_for_test(group_id=2)
    assert not page.is_selected_for_test(group_id=1)
    for button, action in zip(
        page.buttons[1:],
        ("win.update-subscription", "win.edit-subscription", "win.delete-subscription"),
        strict=True,
    ):
        assert button.get_action_name() == action
        assert button.get_action_target_value().get_int32() == 2


def test_buttons_without_subscriptions_are_insensitive(page):
    page.set_data({}, {})
    # «Добавить…» не зависит от выделения: вне приложения её действие
    # просто не находится, поэтому проверяется имя, а не доступность.
    assert page.buttons[0].get_action_name() == "app.add-subscription"
    assert all(not button.get_sensitive() for button in page.buttons[1:])
