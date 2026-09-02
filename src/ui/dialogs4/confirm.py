"""Destructive-action confirmation (GTK4)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw

DELETE = "delete"
CANCEL = "cancel"


def confirm_delete(
    parent,
    heading: str,
    body: str,
    on_confirm: Callable[[], None],
    *,
    confirm_label: str = "Удалить",
) -> Adw.AlertDialog:
    """Ask before deleting something, then run the callback."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response(CANCEL, "Отмена")
    dialog.add_response(DELETE, confirm_label)
    dialog.set_response_appearance(DELETE, Adw.ResponseAppearance.DESTRUCTIVE)
    # Отмена — и ответ по умолчанию, и ответ на Escape: случайный Enter не
    # должен ничего удалять.
    dialog.set_default_response(CANCEL)
    dialog.set_close_response(CANCEL)

    def responded(_dialog, response: str) -> None:
        if response == DELETE:
            on_confirm()

    dialog.connect("response", responded)
    dialog.present(parent)
    return dialog
