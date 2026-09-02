"""TrayController: состояние приложения → иконка, подсказка и меню."""

from __future__ import annotations

import pytest

from src.core.context import AppContext
from src.ui.logic.status import ConnectionState
from src.ui.tray4.controller import TrayController
from tests.support.tray import FakeApp, FakeTrayItem, find_item, labels


@pytest.fixture
def context(tmp_path):
    return AppContext(config_dir=tmp_path)


@pytest.fixture
def controller(context):
    item = FakeTrayItem()
    app = FakeApp()
    tray = TrayController(app, context, item=item, dispatch=lambda fn, *a: fn(*a))
    tray.start()
    yield tray, item, app
    tray.stop()


def test_start_publishes_the_item(controller):
    _tray, item, _app = controller

    assert item.published is True


def test_start_installs_the_initial_menu(controller):
    _tray, item, _app = controller

    assert find_item(item.menus[-1], "Подключить") is not None


def test_start_sets_the_disconnected_icon(controller):
    _tray, item, _app = controller

    assert item.icons[-1] == "tenga-proxy-disconnected"


def test_the_icon_carries_the_theme_directory(context):
    """Панель ищет иконку по имени: без каталога она её не найдёт."""
    item = FakeTrayItem()
    paths: list = []
    item.set_icon = lambda _name, theme_path="": paths.append(theme_path)

    tray = TrayController(FakeApp(), context, item=item, dispatch=lambda fn, *a: fn(*a))
    tray.start()
    try:
        assert paths[-1].endswith("assets/icons")
    finally:
        tray.stop()


def test_the_tooltip_starts_as_disconnected(controller):
    _tray, item, _app = controller

    assert item.tooltips[-1] == "Tenga Proxy: отключено"


def test_setting_the_connected_state_changes_the_icon(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert item.icons[-1] == "tenga-proxy-connected"


def test_setting_the_connecting_state_changes_the_icon(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTING, profile_name="Работа")

    assert item.icons[-1] == "tenga-proxy-connecting"


def test_the_connected_tooltip_names_the_profile(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert item.tooltips[-1] == "Tenga Proxy: Работа"


def test_the_connected_menu_offers_to_disconnect(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert find_item(item.menus[-1], "Отключить") is not None


def test_the_menu_lists_the_profiles_of_the_store(controller, context):
    tray, item, _app = controller
    from src.fmt import parse_link

    bean = parse_link("socks://127.0.0.1:1080#Локальный")
    context.profiles.add_profile(bean)

    tray.refresh()

    assert "Локальный" in labels(find_item(item.menus[-1], "Профили").children)


def test_clicking_an_entry_activates_the_application_action(controller):
    _tray, item, app = controller

    item.on_activate("app.quit", None)

    assert app.activated == [("quit", None)]


def test_clicking_a_profile_entry_passes_the_profile_id(controller):
    _tray, item, app = controller

    item.on_activate("app.connect-profile", 7)

    assert app.activated == [("connect-profile", 7)]


def test_a_left_click_on_the_icon_activates_the_window(controller):
    _tray, item, app = controller

    item.on_primary()

    assert app.activated == [("activate-window", None)]


def test_an_action_that_raises_does_not_escape(context):
    """Клик из трея не должен ронять процесс."""
    item = FakeTrayItem()

    class Exploding:
        def activate_action(self, name, target=None):
            raise RuntimeError("boom")

    tray = TrayController(Exploding(), context, item=item, dispatch=lambda fn, *a: fn(*a))
    tray.start()
    try:
        item.on_activate("app.quit", None)
    finally:
        tray.stop()


def test_a_state_change_of_the_proxy_updates_the_tray(controller, context):
    _tray, item, _app = controller
    before = len(item.menus)

    context.proxy_state.set_running(profile_id=1)

    # Трей слушает состояние прокси: подключение из окна обязано отразиться
    # на иконке без участия окна.
    assert len(item.menus) > before
    assert item.icons[-1] == "tenga-proxy-connected"


def test_the_tooltip_names_the_profile_that_actually_started(controller, context):
    _tray, item, _app = controller
    from src.fmt import parse_link

    entry = context.profiles.add_profile(parse_link("socks://127.0.0.1:1080#Рабочий"))

    context.proxy_state.set_running(profile_id=entry.id)

    assert item.tooltips[-1] == "Tenga Proxy: Рабочий"


def test_the_running_profile_is_checked_in_the_menu(controller, context):
    _tray, item, _app = controller
    from src.fmt import parse_link

    entry = context.profiles.add_profile(parse_link("socks://127.0.0.1:1080#Рабочий"))

    context.proxy_state.set_running(profile_id=entry.id)

    assert find_item(item.menus[-1], "Рабочий").checked is True


def test_stopping_the_proxy_returns_the_disconnected_icon(controller, context):
    _tray, item, _app = controller
    context.proxy_state.set_running(profile_id=1)

    context.proxy_state.set_stopped()

    assert item.icons[-1] == "tenga-proxy-disconnected"


def test_stop_shuts_the_item_down(controller):
    tray, item, _app = controller

    tray.stop()

    assert item.stopped is True


def test_stop_unsubscribes_from_the_proxy_state(controller, context):
    tray, item, _app = controller
    tray.stop()
    before = len(item.icons)

    context.proxy_state.set_running(profile_id=1)

    # Слушатель на уничтоженном элементе привёл бы к вызовам на закрытой шине.
    assert len(item.icons) == before


def test_stop_twice_is_safe(controller):
    tray, _item, _app = controller

    tray.stop()
    tray.stop()


def test_a_state_change_is_delivered_through_the_dispatcher(context):
    """Смена состояния приходит из потока подключения, а D-Bus требует главного."""
    item = FakeTrayItem()
    delivered: list = []
    tray = TrayController(
        FakeApp(), context, item=item, dispatch=lambda fn, *a: delivered.append((fn, a))
    )
    tray.start()
    delivered.clear()

    context.proxy_state.set_running(profile_id=1)

    assert len(delivered) == 1
