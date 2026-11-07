"""Tests for the main window shell."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture
def window(adw_app):
    adw_app.activate()
    return adw_app.get_active_window()


def test_window_has_a_status_card(window):
    from src.ui.widgets.status_card import StatusCard

    assert isinstance(window.status_card, StatusCard)


def test_default_size_comes_from_saved_geometry(adw_app):
    from src.ui.logic.geometry import Geometry, format_geometry

    adw_app.context.config.window_size = format_geometry(Geometry(1000, 800))
    adw_app.activate()
    window = adw_app.get_active_window()

    assert window.get_default_size() == (1000, 800)


def test_close_request_saves_geometry(window, adw_app, monkeypatch):
    from src.ui.logic.geometry import parse_geometry

    monkeypatch.setattr(adw_app, "quit", lambda: None)
    window.set_default_size(980, 660)
    window.emit("close-request")

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (980, 660)


def test_empty_store_asks_to_add_a_server(window, adw_app):
    adw_app.context.proxy_state.is_running = False
    window.refresh_status()
    assert window.status_card.get_title() == "Добавьте сервер или подписку"
    assert window.status_card.logo_button.get_sensitive() is False


def test_status_card_follows_proxy_state(window, adw_app):
    _two_profiles(adw_app)
    adw_app.context.proxy_state.is_running = False
    window.refresh_status()
    assert window.status_card.get_title() == "Отключено"

    adw_app.context.proxy_state.is_running = True
    window.refresh_status()
    assert window.status_card.get_title() == "Подключено"


def test_geometry_is_saved_without_close_request(window, adw_app):
    """Выход по сигналу не эмитирует close-request, геометрия всё равно нужна."""
    from src.ui.logic.geometry import parse_geometry

    window.set_default_size(1010, 640)
    window.save_geometry()

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (1010, 640)


def test_window_unsubscribes_from_proxy_state_on_close(window, adw_app, monkeypatch):
    """Слушатель мёртвого окна обратился бы к уничтоженным виджетам."""
    monkeypatch.setattr(adw_app, "quit", lambda: None)
    state = adw_app.context.proxy_state
    before = len(state._state_listeners)

    window.close()
    window.destroy()

    assert len(state._state_listeners) == before - 1


def test_pages_are_real_widgets(window):
    from src.ui.pages.monitoring import MonitoringPage
    from src.ui.pages.profiles import ProfilesPage

    assert isinstance(window.profiles_page, ProfilesPage)
    assert not hasattr(window, "subscriptions_page")
    assert isinstance(window.monitoring_page, MonitoringPage)


def test_refresh_pages_survives_an_empty_store(window):
    window.refresh_pages()
    assert window.profiles_page.get_visible_state() == "empty"


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

    from gi.repository import GLib

    window.lookup_action("update-subscription").activate(GLib.Variant("i", group.id))
    adw_app.wait_for_subscriptions_for_test()

    assert updated == [group.id]


def _subscription_with_links(adw_app, **links):
    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/list"
    for name, value in links.items():
        setattr(group, name, value)
    return group


def test_the_subscription_page_link_is_opened(window, adw_app, monkeypatch):
    from gi.repository import GLib

    group = _subscription_with_links(adw_app, sub_web_page_url="https://provider.example/account")
    opened: list[str] = []
    monkeypatch.setattr(window, "_launch_uri", opened.append)

    window.lookup_action("open-subscription-page").activate(GLib.Variant("i", group.id))

    assert opened == ["https://provider.example/account"]


def test_the_support_link_is_opened(window, adw_app, monkeypatch):
    from gi.repository import GLib

    group = _subscription_with_links(adw_app, sub_support_url="tg://resolve?domain=provider")
    opened: list[str] = []
    monkeypatch.setattr(window, "_launch_uri", opened.append)

    window.lookup_action("open-subscription-support").activate(GLib.Variant("i", group.id))

    assert opened == ["tg://resolve?domain=provider"]


def test_an_unsafe_link_is_not_opened(window, adw_app, monkeypatch):
    """profiles.json можно поправить руками: ссылка проверяется и перед открытием."""
    from gi.repository import GLib

    group = _subscription_with_links(adw_app, sub_web_page_url="file:///etc/passwd")
    opened: list[str] = []
    monkeypatch.setattr(window, "_launch_uri", opened.append)

    window.lookup_action("open-subscription-page").activate(GLib.Variant("i", group.id))

    assert opened == []


# --- действия строк (этап 3) ---

ROW_ACTIONS = {
    "connect-profile",
    "edit-profile",
    "delete-profile",
    "profile-routing",
    "test-profile",
    "toggle-group",
    "edit-group",
    "delete-group",
    "update-subscription",
    "edit-subscription",
    "delete-subscription",
    "open-subscription-page",
    "open-subscription-support",
}


def test_the_window_registers_the_row_actions(window):
    assert set(window.list_actions()) >= ROW_ACTIONS


def test_the_row_actions_take_an_integer(window):
    from gi.repository import GLib

    action = window.lookup_action("edit-profile")
    assert action.get_parameter_type().equal(GLib.VariantType.new("i"))


def test_connecting_shows_the_intermediate_state(window):
    window.show_connecting("Альфа")
    assert "Альфа" in window.status_card.get_subtitle()


def test_a_connection_error_survives_the_status_refresh(window, adw_app):
    # Контроллер после show_error сразу перерисовывает окно.
    adw_app.context.proxy_state.is_running = False
    window.show_error("xray-core не запустился")
    window.refresh_status()

    assert window.status_card.get_title() == "Ошибка"
    assert window.status_card.get_health() == "xray-core не запустился"
    assert window.status_card.get_button_label() == "Повторить"


def test_disconnected_card_names_the_last_used_profile(window, adw_app):
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )
    store.mark_used(entry.id)
    adw_app.context.proxy_state.is_running = False
    window.refresh_pages()
    window.refresh_status()

    assert window.status_card.get_title() == "Отключено"
    assert window.status_card.get_subtitle() == "Проба"


def test_disconnected_card_follows_the_selected_profile(window, adw_app):
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    for name in ("Первый", "Второй"):
        store.parse_and_add_link(
            f"vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#{name}",
            group_id=group.id,
        )
    adw_app.context.proxy_state.is_running = False
    window.refresh_pages()
    window.profiles_page.expand_all()

    second = next(p for p in store.profiles.values() if p.name == "Второй")
    window.profiles_page.select_profile(second.id)

    assert window.status_card.get_subtitle() == "Второй"


def _two_profiles(adw_app):
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    for name in ("Первый", "Второй"):
        store.parse_and_add_link(
            f"vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#{name}",
            group_id=group.id,
        )
    by_name = {p.name: p for p in store.profiles.values()}
    return by_name["Первый"], by_name["Второй"]


def test_selecting_another_profile_offers_an_explicit_switch(window, adw_app):
    first, second = _two_profiles(adw_app)
    adw_app.context.proxy_state.is_running = True
    adw_app.context.proxy_state.started_profile_id = first.id
    window.refresh_pages()
    window.profiles_page.expand_all()

    window.profiles_page.select_profile(second.id)
    assert window.profiles_page.switch_button.get_visible() is True
    assert window.status_card.get_subtitle() == "Первый"
    assert not hasattr(window.status_card, "switch_button")

    window.profiles_page.select_profile(first.id)
    assert window.profiles_page.switch_button.get_visible() is False


def test_the_switch_connects_the_selected_profile(window, adw_app, monkeypatch):
    first, second = _two_profiles(adw_app)
    adw_app.context.proxy_state.is_running = True
    adw_app.context.proxy_state.started_profile_id = first.id
    window.refresh_pages()
    window.profiles_page.expand_all()
    window.profiles_page.select_profile(second.id)

    connected = []
    monkeypatch.setattr(adw_app.controller, "connect_profile", connected.append)
    window.profiles_page.switch_button.emit("clicked")

    assert connected == [second.id]


def test_a_started_session_is_not_shown_as_checked(window, adw_app):
    adw_app.context.proxy_state.is_running = True
    window.refresh_status()

    assert window.status_card.get_title() == "Подключено"
    assert window.status_card.get_health() == "Проверка соединения ещё не выполнена"


def test_toggle_group_expands_and_collapses(window, adw_app):
    from gi.repository import GLib

    from src.fmt import parse_link

    store = adw_app.context.profiles
    group = store.add_group("Дом")
    store.add_profile(
        parse_link("vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp#A"),
        group_id=group.id,
    )
    window.refresh_pages()
    before = window.profiles_page.get_visible_row_count()

    # Действие вызывается напрямую: window.activate_action() ставит его в
    # очередь главного цикла, которая в тесте не крутится.
    window.lookup_action("toggle-group").activate(GLib.Variant("i", group.id))

    assert window.profiles_page.get_visible_row_count() > before


def _drain_main_loop() -> None:
    from gi.repository import GLib

    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


def _subscription_in(adw_app, window):
    store = adw_app.context.profiles
    group = store.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/list"
    window.refresh_pages()
    return group


def test_traffic_tick_keeps_the_open_subscription_menu(window, adw_app):
    """Счётчик трафика тикает раз в секунду: пересборка строк закрывала их меню."""
    group = _subscription_in(adw_app, window)
    state = adw_app.context.proxy_state
    state.set_running(-1, "proxy")
    _drain_main_loop()
    adw_app.activate_action("settings", None)
    subscriptions = adw_app.settings_dialog.subscriptions_list
    menu_button = subscriptions.get_menu_button_for_test(group_id=group.id)

    state.upload_bytes += 1024
    state.notify_listeners()
    _drain_main_loop()

    assert subscriptions.get_menu_button_for_test(group_id=group.id) is menu_button


def test_traffic_tick_still_redraws_the_status_and_monitoring(window, adw_app, monkeypatch):
    state = adw_app.context.proxy_state
    state.set_running(-1, "proxy")
    _drain_main_loop()
    drawn: list[str] = []
    monkeypatch.setattr(window, "refresh_status", lambda: drawn.append("status"))
    monkeypatch.setattr(window, "refresh_monitoring", lambda: drawn.append("monitoring"))

    state.notify_listeners()
    _drain_main_loop()

    assert sorted(drawn) == ["monitoring", "status"]


def test_connecting_and_disconnecting_rebuild_the_pages(window, adw_app):
    """Смена активного сервера видна в списке, поэтому строки пересобираются."""
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )
    window.refresh_pages()
    state = adw_app.context.proxy_state

    state.set_running(entry.id, "proxy")
    _drain_main_loop()
    assert window.profiles_page.get_active_titles() == ["Проба"]

    state.set_stopped()
    _drain_main_loop()
    assert window.profiles_page.get_active_titles() == []


def test_blocked_banner_follows_the_traffic_state(window):
    state = window._context.proxy_state
    assert not window.blocked_banner.get_revealed()

    state.traffic_blocked = True
    window.refresh_status()

    assert window.blocked_banner.get_revealed()
    assert window.status_card._title.get_text() == "Трафик заблокирован"

    state.traffic_blocked = False
    window.refresh_status()

    assert not window.blocked_banner.get_revealed()


# --- компоновка как в Qt ------------------------------------------------------


def _menu_labels(model):
    labels = []
    for index in range(model.get_n_items()):
        label = model.get_item_attribute_value(index, "label", None)
        if label is not None:
            labels.append(label.get_string())
        for link in ("section", "submenu"):
            child = model.get_item_link(index, link)
            if child is not None:
                labels.extend(_menu_labels(child))
    return labels


def test_window_has_a_side_panel_and_two_right_pages(window):
    from gi.repository import Gtk

    assert not hasattr(window, "view_stack")
    assert not hasattr(window, "view_switcher")
    assert window.right_stack.get_child_by_name("servers") is not None
    assert window.right_stack.get_child_by_name("monitoring").get_child().get_child() is (
        window.monitoring_page
    )
    assert window.right_stack.get_visible_child_name() == "servers"
    assert isinstance(window.columns, Gtk.Box)
    assert window.columns.get_first_child() is window.panel_clamp
    assert window.panel_clamp.get_child() is window.status_card


def test_header_shows_the_page_title_and_actions(window):
    assert window.page_title.get_text() == "Серверы"
    assert window.back_button.get_visible() is False
    assert window.settings_button.get_label() == "Настройки"
    assert window.settings_button.get_action_name() == "app.settings"
    assert window.menu_button.get_tooltip_text() == "Главное меню"
    assert not hasattr(window, "search_button")


def test_main_menu_follows_the_shared_list(window):
    from src.ui.logic.menus import MAIN_MENU

    labels = _menu_labels(window.menu_button.get_menu_model())
    assert labels == [label for _n, label in MAIN_MENU]
    assert "Журнал…" in labels


def test_footer_has_the_diagnostics_toggle_and_latency(window):
    assert window.diagnostics_toggle.get_label() == "Диагностика"
    assert window.latency_button.get_label() == "Проверить задержку"
    assert window.latency_button.get_action_name() == "app.test-latency"


def test_search_action_focuses_the_entry_and_returns_to_servers(window, adw_app):
    window.present()
    window.diagnostics_toggle.set_active(True)
    adw_app.activate_action("search", None)
    assert window.right_stack.get_visible_child_name() == "servers"
    _drain_main_loop()
    assert window.profiles_page.search_entry.get_focus_child() is not None or (
        window.get_focus() is not None
        and window.get_focus().is_ancestor(window.profiles_page.search_entry)
    )


def test_short_window_makes_the_panel_compact(window):
    from gi.repository import GLib

    window.set_default_size(1000, 560)
    window.present()
    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + 5_000_000
    while window.get_current_breakpoint() is None and GLib.get_monotonic_time() < deadline:
        context.iteration(True)

    assert window.status_card.get_property("compact") is True


def test_ping_button_tests_the_profile(window, adw_app, monkeypatch):
    first, _second = _two_profiles(adw_app)
    tested = []
    monkeypatch.setattr(adw_app.controller, "test_latency_for", tested.append)
    window.profiles_page.emit("profile-ping", first.id)
    assert tested == [first.id]


def test_toggle_switches_the_right_page_and_header(window, monkeypatch):
    monkeypatch.setattr(window.monitoring_page, "refresh_diagnostics", lambda *_a: None)
    window.present()
    window.diagnostics_toggle.set_active(True)
    assert window.right_stack.get_visible_child_name() == "monitoring"
    assert window.page_title.get_text() == "Диагностика"
    assert window.back_button.get_visible() is True
    assert window.monitoring_page.log_timer_running_for_test() is True

    window.back_button.emit("clicked")
    assert window.right_stack.get_visible_child_name() == "servers"
    assert window.page_title.get_text() == "Серверы"
    assert window.diagnostics_toggle.get_active() is False
    assert window.monitoring_page.log_timer_running_for_test() is False


def test_show_log_action_opens_diagnostics_and_focuses_the_log(window, adw_app, monkeypatch):
    monkeypatch.setattr(window.monitoring_page, "refresh_diagnostics", lambda *_a: None)
    adw_app.activate_action("show-log", None)
    _drain_main_loop()
    assert window.right_stack.get_visible_child_name() == "monitoring"
    assert window.get_focus() is window.monitoring_page.log_view


def test_switching_pages_keeps_query_and_selection(window, adw_app, monkeypatch):
    monkeypatch.setattr(window.monitoring_page, "refresh_diagnostics", lambda *_a: None)
    first, _second = _two_profiles(adw_app)
    window.refresh_pages()
    window.profiles_page.search_entry.set_text("Перв")
    window.profiles_page.set_query("Перв")
    window.profiles_page.expand_all()
    window.profiles_page.select_profile(first.id)

    window.diagnostics_toggle.set_active(True)
    window.diagnostics_toggle.set_active(False)

    assert window.profiles_page.search_entry.get_text() == "Перв"
    assert window.profiles_page.get_selected_profile_id() == first.id


def test_hiding_the_window_stops_the_log_timer(window, monkeypatch):
    monkeypatch.setattr(window.monitoring_page, "refresh_diagnostics", lambda *_a: None)
    window.present()
    window.diagnostics_toggle.set_active(True)
    assert window.monitoring_page.log_timer_running_for_test() is True
    window.set_visible(False)
    assert window.monitoring_page.log_timer_running_for_test() is False


def test_close_quits_when_close_to_tray_is_off(window, adw_app, monkeypatch):
    quits = []
    monkeypatch.setattr(adw_app, "quit", lambda: quits.append(True))
    monkeypatch.setattr(adw_app, "tray_visible", lambda: True)
    adw_app.context.config.close_to_tray = False
    window.emit("close-request")
    assert quits == [True]


def test_close_quits_without_a_tray(window, adw_app, monkeypatch):
    quits = []
    monkeypatch.setattr(adw_app, "quit", lambda: quits.append(True))
    monkeypatch.setattr(adw_app, "tray_visible", lambda: False)
    adw_app.context.config.close_to_tray = True
    window.emit("close-request")
    assert quits == [True]


def test_close_hides_into_the_tray(window, adw_app, monkeypatch):
    quits = []
    monkeypatch.setattr(adw_app, "quit", lambda: quits.append(True))
    monkeypatch.setattr(adw_app, "tray_visible", lambda: True)
    adw_app.context.config.close_to_tray = True
    window.present()
    handled = window.emit("close-request")
    assert handled is True
    assert quits == []
    assert window.get_visible() is False


def test_hide_window_action_closes_like_the_close_button(window, adw_app, monkeypatch):
    quits = []
    monkeypatch.setattr(adw_app, "quit", lambda: quits.append(True))
    monkeypatch.setattr(adw_app, "tray_visible", lambda: True)
    adw_app.context.config.close_to_tray = True
    window.present()
    adw_app.activate_action("hide-window", None)
    assert window.get_visible() is False
    assert quits == []


def test_open_settings_follow_store_changes(window, adw_app):
    adw_app.activate_action("settings", None)
    dialog = adw_app.settings_dialog
    assert dialog.subscriptions_list.get_visible_state() == "empty"

    group = _subscription_in(adw_app, window)
    assert dialog.subscriptions_list.get_selected() == group.id


def test_forms_open_over_the_settings(window, adw_app):
    adw_app.activate_action("settings", None)
    settings = adw_app.settings_dialog
    adw_app.activate_action("add-subscription", None)
    form = adw_app.current_dialog
    assert form is not settings
    assert adw_app.settings_dialog is settings

    # Над формой ещё одна не открывается.
    adw_app.activate_action("add-profile", None)
    assert adw_app.current_dialog is form

    # Анимация закрытия в тестах не проигрывается (см. `_simulate_close` в
    # тестах приложения): слот освобождается так, как это сделал бы `closed`.
    adw_app._on_dialog_closed(form)
    assert adw_app.current_dialog is settings
    adw_app._on_dialog_closed(settings)
    assert adw_app.current_dialog is None


def test_the_right_column_fits_the_minimum_height(window):
    """Диагностика выше окна 900×540: её страница прокручивается, а не растит стек."""
    from gi.repository import Gtk

    from src.ui.logic.geometry import MIN_HEIGHT

    minimum, _natural, _b1, _b2 = window.right_stack.measure(Gtk.Orientation.VERTICAL, -1)
    assert minimum < MIN_HEIGHT - 100


def test_install_action_is_registered(adw_app):
    assert adw_app.lookup_action("install-app-update") is not None
