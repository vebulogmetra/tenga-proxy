"""Tests for the main window shell."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture
def window(adw_app):
    adw_app.activate()
    return adw_app.get_active_window()


def test_window_has_three_pages(window):
    names = [page.get_name() for page in window.view_stack.get_pages()]
    assert names == ["profiles", "subscriptions", "monitoring"]


def test_window_has_a_status_card(window):
    from src.ui.widgets.status_card import StatusCard

    assert isinstance(window.status_card, StatusCard)


def test_narrow_window_moves_the_switcher_down(window):
    """Проверяется поведение, а не факт установки: list_breakpoints() есть только с 1.6."""
    from gi.repository import GLib

    window.set_default_size(420, 700)
    window.present()

    context = GLib.MainContext.default()
    for _ in range(200):
        if not context.pending():
            break
        context.iteration(False)

    assert window.get_current_breakpoint() is not None
    assert window.view_switcher_bar.get_reveal() is True
    assert window.view_switcher.get_visible() is False


def test_default_size_comes_from_saved_geometry(adw_app):
    from src.ui.logic.geometry import Geometry, format_geometry

    adw_app.context.config.window_size = format_geometry(Geometry(900, 800))
    adw_app.activate()
    window = adw_app.get_active_window()

    assert window.get_default_size() == (900, 800)


def test_close_request_saves_geometry(window, adw_app):
    from src.ui.logic.geometry import parse_geometry

    window.set_default_size(880, 660)
    window.emit("close-request")

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (880, 660)


def test_status_card_follows_proxy_state(window, adw_app):
    adw_app.context.proxy_state.is_running = False
    window.refresh_status()
    assert window.status_card.get_title() == "Отключено"

    adw_app.context.proxy_state.is_running = True
    window.refresh_status()
    assert window.status_card.get_title() == "Подключено"


def test_default_width_is_wider_than_the_narrow_breakpoint():
    """Окно по умолчанию не должно открываться в компактном режиме."""
    from src.ui.logic.geometry import DEFAULT_GEOMETRY
    from src.ui.window import NARROW_WIDTH

    assert DEFAULT_GEOMETRY.width > NARROW_WIDTH


def test_geometry_is_saved_without_close_request(window, adw_app):
    """Выход по сигналу не эмитирует close-request, геометрия всё равно нужна."""
    from src.ui.logic.geometry import parse_geometry

    window.set_default_size(910, 640)
    window.save_geometry()

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (910, 640)


def test_window_unsubscribes_from_proxy_state_on_close(window, adw_app):
    """Слушатель мёртвого окна обратился бы к уничтоженным виджетам."""
    state = adw_app.context.proxy_state
    before = len(state._state_listeners)

    window.close()
    window.destroy()

    assert len(state._state_listeners) == before - 1


def test_pages_are_real_widgets(window):
    from src.ui.pages.monitoring import MonitoringPage
    from src.ui.pages.profiles import ProfilesPage
    from src.ui.pages.subscriptions import SubscriptionsPage

    assert isinstance(window.profiles_page, ProfilesPage)
    assert isinstance(window.subscriptions_page, SubscriptionsPage)
    assert isinstance(window.monitoring_page, MonitoringPage)


def test_search_toggles_the_bar_of_the_visible_page(window):
    window.view_stack.set_visible_child_name("profiles")
    window.set_search_enabled(True)
    assert window.profiles_page.search_bar.get_search_mode() is True

    window.view_stack.set_visible_child_name("subscriptions")
    window.set_search_enabled(True)
    assert window.subscriptions_page.search_bar.get_search_mode() is True


def test_search_is_disabled_on_the_monitoring_page(window):
    """Мониторинг — не список, искать там нечего."""
    window.view_stack.set_visible_child_name("monitoring")
    window.set_search_enabled(True)
    assert window.search_button.get_sensitive() is False


def test_switching_pages_closes_the_previous_search(window):
    window.view_stack.set_visible_child_name("profiles")
    window.set_search_enabled(True)

    window.view_stack.set_visible_child_name("subscriptions")

    assert window.profiles_page.search_bar.get_search_mode() is False


def test_refresh_pages_survives_an_empty_store(window):
    window.refresh_pages()
    assert window.profiles_page.get_visible_state() == "empty"
    assert window.subscriptions_page.get_visible_state() == "empty"


def test_refresh_pages_marks_the_active_profile(window, adw_app):
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )
    assert entry is not None

    adw_app.context.proxy_state.is_running = True
    adw_app.context.proxy_state.started_profile_id = entry.id
    window.refresh_pages()

    assert window.profiles_page.get_active_titles() == ["Проба"]


def test_monitoring_page_is_updated_on_refresh(window):
    window.refresh_pages()
    assert window.monitoring_page.get_value("Прокси") == "Не запущен"


def test_profile_activation_reaches_the_application(window, adw_app):
    """Двойной щелчок по профилю выбирает его для подключения."""
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )
    window.refresh_pages()

    selected: list[int] = []
    adw_app.set_profile_activation_handler(selected.append)

    window.profiles_page.expand_all()
    window.profiles_page.emit_activation_for_test(profile_id=entry.id)

    assert selected == [entry.id]


def test_subscription_update_reaches_the_application(window, adw_app):
    store = adw_app.context.profiles
    group = store.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/list"
    window.refresh_pages()

    updated: list[int] = []
    adw_app.set_subscription_updater(lambda gid, _url: updated.append(gid) or 1)

    window.subscriptions_page.click_update_for_test(group_id=group.id)
    adw_app.wait_for_subscriptions_for_test()

    assert updated == [group.id]
