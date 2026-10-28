"""QtTrayItem: меню из модели трея, клики и иконки."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QSystemTrayIcon

from src.ui.logic.status import ConnectionState
from src.ui.qt.tray import QtTrayItem, icon_file
from src.ui.tray.controller import TrayController
from src.ui.tray.dbusmenu import MenuItem, separator
from src.ui.tray.icons import icons_directory
from src.ui.tray.menu import build_menu

pytestmark = pytest.mark.qt


def _labels(menu):
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def test_menu_follows_the_model(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu(
        [
            MenuItem("Статус", enabled=False),
            separator(),
            MenuItem("Подключить", action="app.connect"),
            MenuItem("Профили", children=[MenuItem("A", action="app.connect-profile", target=1)]),
            MenuItem("Скрытый", visible=False),
        ]
    )

    actions = item.menu.actions()
    assert _labels(item.menu) == ["Статус", "Подключить", "Профили"]
    assert actions[1].isSeparator()
    assert not actions[0].isEnabled()
    assert _labels(actions[3].menu()) == ["A"]


def test_triggered_entry_reports_action_and_target(qapp):
    item = QtTrayItem(available=lambda: True)
    seen = []
    item.set_on_activate(lambda name, target: seen.append((name, target)))
    item.set_menu(
        [MenuItem("Профили", children=[MenuItem("A", action="app.connect-profile", target=7)])]
    )

    item.menu.actions()[0].menu().actions()[0].trigger()

    assert seen == [("app.connect-profile", 7)]


def test_checked_entry_is_checkable(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu([MenuItem("A", action="app.connect-profile", target=1, checked=True)])

    action = item.menu.actions()[0]
    assert action.isCheckable() and action.isChecked()


def test_flag_prefix_becomes_an_icon(qapp):
    item = QtTrayItem(available=lambda: True)
    item.set_menu([MenuItem("🇩🇪 Берлин", action="app.connect-profile", target=1)])

    action = item.menu.actions()[0]
    assert action.text() == "Берлин"
    assert not action.icon().isNull()


def test_left_click_is_the_primary_action(qapp):
    item = QtTrayItem(available=lambda: True)
    clicks = []
    item.set_on_primary(lambda: clicks.append(1))

    item._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    item._on_activated(QSystemTrayIcon.ActivationReason.Context)

    assert clicks == [1]


def test_publish_refuses_without_a_tray(qapp):
    item = QtTrayItem(available=lambda: False)

    with pytest.raises(RuntimeError):
        item.publish()


def test_icons_prefer_the_windows_ico():
    path = icon_file("tenga-proxy-connected", str(icons_directory()))

    assert path.suffix == ".ico" and path.is_file()


def test_tray_controller_drives_the_qt_item(qapp, tmp_path):
    from src.core.context import AppContext

    context = AppContext(config_dir=tmp_path)
    item = QtTrayItem(available=lambda: True)
    activated = []
    app = type("App", (), {"activate_action": lambda _s, n, t=None: activated.append((n, t))})()
    controller = TrayController(app, context, item=item, dispatch=lambda fn, *a: fn(*a))

    controller.start()
    controller.set_state(ConnectionState.CONNECTED, "Проба")
    try:
        labels = _labels(item.menu)
        assert labels[0] == "Статус: Проба"
        assert "Отключить" in labels
        item.menu.actions()[2].trigger()
        assert activated == [("disconnect", None)]
    finally:
        controller.stop()


def test_menu_of_the_real_builder_renders(qapp):
    item = QtTrayItem(available=lambda: True)

    item.set_menu(build_menu(ConnectionState.DISCONNECTED, []))

    assert _labels(item.menu)[-1] == "Выход"
