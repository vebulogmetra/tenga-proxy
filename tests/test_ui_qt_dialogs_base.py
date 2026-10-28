"""Каркас Qt-диалогов: форма, выбор по ключу, автосохранение, ошибки полей."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QCheckBox, QLineEdit

from src.ui.qt.dialogs.base import Debounce, FormDialog, KeyedCombo, mark_error, watch
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


def test_form_buttons_and_status(qapp):
    dialog = FormDialog("Заголовок", "Готово")

    assert dialog.windowTitle() == "Заголовок"
    assert dialog.confirm_button.text() == "Готово"
    assert dialog.confirm_button.isDefault()
    dialog.set_status("Ошибка", error=True)
    assert not dialog.status.isHidden()
    assert dialog.status.property("error") is True
    dialog.set_status("")
    assert dialog.status.isHidden()


def test_keyed_combo_falls_back_to_the_first_key(qapp):
    combo = KeyedCombo(["a", "b"], {"a": "Альфа", "b": "Бета"})

    combo.select("b")
    assert combo.selected() == "b" and combo.currentText() == "Бета"
    combo.select("из другой версии")
    assert combo.selected() == "a"


def test_debounce_runs_once_and_flushes(qapp):
    calls = []
    debounce = Debounce(lambda: calls.append(1), delay_ms=10)

    debounce.queue()
    debounce.queue()
    wait_until(lambda: calls)
    for _ in range(5):
        process_events()
    assert calls == [1]

    debounce.queue()
    debounce.flush()
    assert calls == [1, 1] and not debounce.pending
    debounce.flush()
    assert calls == [1, 1]


def test_watch_connects_every_field(qapp):
    seen = []
    edit, box = QLineEdit(), QCheckBox()
    watch([edit, box], lambda *_: seen.append(1))

    edit.setText("x")
    box.setChecked(True)

    assert seen == [1, 1]


def test_mark_error_sets_tooltip(qapp):
    edit = QLineEdit()

    mark_error(edit, "Плохо")
    assert edit.property("error") is True and edit.toolTip() == "Плохо"
    mark_error(edit, None)
    assert edit.property("error") is False and edit.toolTip() == ""
