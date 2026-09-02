"""Keyboard shortcut reference (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

# Пары «сочетание — что делает». Держатся здесь, а не собираются из `_ACCELS`:
# у действия нет человекочитаемого описания, а порядок в справке смысловой.
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Соединение",
        [
            ("<Control>Return", "Подключить или отключить"),
            ("<Control>t", "Проверить задержку"),
        ],
    ),
    (
        "Профили и подписки",
        [
            ("<Control>n", "Добавить профиль"),
            ("<Control><Shift>n", "Добавить подписку"),
            ("F5", "Обновить подписки"),
            ("<Control>f", "Поиск"),
        ],
    ),
    (
        "Приложение",
        [
            ("<Control>comma", "Настройки"),
            ("<Control>w", "Скрыть окно"),
            ("<Control>q", "Выход"),
        ],
    ),
]


class ShortcutsDialog(Adw.Dialog):
    """Lists every keyboard shortcut of the application."""

    __gtype_name__ = "TengaShortcutsDialog"

    def __init__(self) -> None:
        super().__init__()
        self.set_title("Сочетания клавиш")
        self.set_content_width(460)
        self.set_content_height(560)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.set_child(toolbar)

        page = Adw.PreferencesPage()
        # Явная ширина: без неё описания сжимаются в столбик по одной букве.
        page.set_size_request(420, -1)
        toolbar.set_content(page)

        for title, entries in SHORTCUTS:
            group = Adw.PreferencesGroup(title=title)
            page.add(group)
            for accelerator, description in entries:
                group.add(_shortcut_row(accelerator, description))


def _shortcut_row(accelerator: str, description: str) -> Adw.ActionRow:
    row = Adw.ActionRow(title=description)
    label = Gtk.ShortcutLabel(accelerator=accelerator, valign=Gtk.Align.CENTER)
    row.add_suffix(label)
    return row
