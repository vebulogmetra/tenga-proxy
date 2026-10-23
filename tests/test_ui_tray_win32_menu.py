"""Дерево меню трея → последовательность вызовов AppendMenuW."""

from __future__ import annotations

from src.ui.logic.status import ConnectionState
from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator
from src.ui.tray.menu import build_menu
from src.ui.tray.win32.menu_ops import Entry, Popup, Separator, menu_ops, win32_label


def test_ampersand_is_escaped():
    assert win32_label("Tom & Jerry") == "Tom && Jerry"


def test_flat_items_keep_model_ids_and_flags():
    model = MenuModel(
        [
            MenuItem("Статус", enabled=False),
            separator(),
            MenuItem("Подключить", action="app.connect"),
        ]
    )

    ops = menu_ops(model)

    assert ops == [
        Entry(id=1, label="Статус", enabled=False, checked=False),
        Separator(),
        Entry(id=3, label="Подключить", enabled=True, checked=False),
    ]


def test_children_become_popup():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A", checked=True)])])

    ops = menu_ops(model)

    assert ops == [
        Popup(label="Профили", children=[Entry(id=2, label="A", enabled=True, checked=True)])
    ]


def test_invisible_items_are_skipped():
    model = MenuModel([MenuItem("x", visible=False), MenuItem("y")])

    assert [op.label for op in menu_ops(model)] == ["y"]


def test_real_menu_converts():
    model = MenuModel(build_menu(ConnectionState.DISCONNECTED, []))

    assert any(isinstance(op, Popup) for op in menu_ops(model))
