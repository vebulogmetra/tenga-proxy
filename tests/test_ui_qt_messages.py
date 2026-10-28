"""Подтверждения, импорт маршрутизации, сочетания клавиш, «О программе»."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.qt


def test_confirmation_defaults_to_cancel(qapp):
    from src.ui.controller import CONFIRM_DELETE
    from src.ui.qt.dialogs.confirm import build_confirmation

    confirmed = []
    box = build_confirmation(
        CONFIRM_DELETE, "Удалить?", "Текст", lambda: confirmed.append(1), confirm_label="Очистить"
    )

    assert box.defaultButton().text() == "Отмена"
    assert box.escapeButton().text() == "Отмена"
    next(b for b in box.buttons() if b.text() == "Очистить").click()
    assert confirmed == [1]


def test_url_change_buttons(qapp):
    from src.ui.controller import CONFIRM_URL_CHANGE
    from src.ui.qt.dialogs.confirm import build_confirmation

    box = build_confirmation(CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: None)

    assert sorted(b.text() for b in box.buttons()) == ["Оставить", "Сменить"]


def test_routing_import_lists_rows_and_confirms_only_on_import(qapp):
    from src.ui.logic.routing_import import REST_LABEL, ImportRow
    from src.ui.qt.dialogs.routing_import import RoutingImportDialog

    rows = [
        ImportRow("Профиль", "Дом"),
        ImportRow("Через прокси", "2 правила: +2, −0", ("+ a.example", "+ b.example")),
        ImportRow(REST_LABEL, "через прокси", warning=True),
    ]
    confirmed = []
    dialog = RoutingImportDialog(rows, lambda: confirmed.append(1))

    assert dialog.row_titles() == ["Профиль", "Через прокси", REST_LABEL]
    assert dialog.tree.topLevelItem(1).childCount() == 2
    assert dialog.cancel_button.isDefault()
    dialog.reject()
    assert confirmed == []
    dialog.import_button.click()
    assert confirmed == [1]


def test_shortcuts_cover_every_action_once(qapp):
    from src.ui.qt.dialogs.shortcuts import SECTIONS, SHORTCUTS, ShortcutsDialog, native_text

    listed = [action for _title, entries in SECTIONS for action, _text in entries]
    assert sorted(listed) == sorted(SHORTCUTS)
    assert native_text("add-profile") == "Ctrl+N"
    ShortcutsDialog()


def test_about_copies_both_versions(qapp):
    from src.ui.qt.dialogs.about import AboutDialog

    dialog = AboutDialog("0.20.0", "25.1.1")
    dialog.copy_button.click()

    assert QApplication.clipboard().text() == "Veblock 0.20.0\nxray-core 25.1.1"
    assert dialog.version_label.text() == "Версия 0.20.0"
