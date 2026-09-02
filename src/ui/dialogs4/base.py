"""Shared shell for the form dialogs."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk

DEFAULT_WIDTH = 520
DEFAULT_HEIGHT = 420


class FormDialog(Adw.Dialog):
    """An Adw.Dialog with a header bar, a cancel and a confirm button.

    `Adw.Dialog` не имеет ни встроенной шапки, ни кнопок ответа: в отличие от
    GTK3-диалога, он лишь накладывается на окно. Общий каркас собран здесь,
    чтобы четыре формы не повторяли одну и ту же обвязку.
    """

    def __init__(self, title: str, confirm_label: str) -> None:
        super().__init__()
        self.set_title(title)
        self.set_content_width(DEFAULT_WIDTH)
        self.set_content_height(DEFAULT_HEIGHT)

        self._toolbar = Adw.ToolbarView()
        self.set_child(self._toolbar)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.set_show_start_title_buttons(False)

        cancel = Gtk.Button(label="Отмена")
        cancel.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel)

        self.confirm_button = Gtk.Button(label=confirm_label)
        self.confirm_button.add_css_class("suggested-action")
        self.confirm_button.connect("clicked", self._on_confirm)
        header.pack_end(self.confirm_button)

        self._toolbar.add_top_bar(header)

        self.page = Adw.PreferencesPage()
        self._toolbar.set_content(self.page)

    def set_content_widget(self, widget: Gtk.Widget) -> None:
        """Replace the preferences page with another widget."""
        self._toolbar.set_content(widget)

    def _on_confirm(self, _button: Gtk.Button) -> None:
        """Hook for subclasses; the default just closes the dialog."""
        self.close()


def copy_to_clipboard(text: str) -> None:
    """Put text into the system clipboard, if there is a display."""
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def read_clipboard(on_text) -> None:
    """Read the clipboard and hand the text to a callback.

    Чтение в GTK4 асинхронное: синхронного `wait_for_text` из GTK3 больше нет,
    поэтому вызывающий получает текст колбэком.
    """
    display = Gdk.Display.get_default()
    if display is None:
        return

    clipboard = display.get_clipboard()

    def done(source, result) -> None:
        try:
            text = source.read_text_finish(result)
        except Exception:
            # Буфер может держать не-текст (изображение, файлы) — молча
            # ничего не вставляем.
            return
        if text:
            on_text(text.strip())

    clipboard.read_text_async(None, done)
