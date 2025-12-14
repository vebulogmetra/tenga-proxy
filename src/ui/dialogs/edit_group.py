from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from src.db.profiles import ProfileGroup


class EditGroupDialog(Gtk.Dialog):
    """Dialog for editing group name."""

    def __init__(
        self,
        parent: Gtk.Window | None = None,
        group: ProfileGroup | None = None,
    ):
        super().__init__(
            title="Редактировать группу",
            transient_for=parent,
            flags=0,
        )
        self.set_wmclass("tenga-proxy", "tenga-proxy")
        self.set_role("tenga-proxy")
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.connect("realize", self._on_realize)

        self.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,
            Gtk.ResponseType.OK,
        )

        self.set_default_size(400, 150)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)

        self._group = group
        self._name_entry: Gtk.Entry | None = None
        self._error_label: Gtk.Label | None = None

        self._setup_ui()

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Handle window realization."""
        window = self.get_window()
        if window:
            try:
                window.set_wmclass("tenga-proxy", "tenga-proxy")
                self.set_skip_taskbar_hint(True)
            except Exception:
                pass

    def _setup_ui(self) -> None:
        """Setup UI."""
        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(15)
        content.set_margin_end(15)
        content.set_margin_top(10)
        content.set_margin_bottom(10)

        info_label = Gtk.Label()
        if self._group and self._group.is_subscription:
            info_label.set_markup("<b>Редактировать подписку</b>")
        else:
            info_label.set_markup("<b>Редактировать группу</b>")
        info_label.set_halign(Gtk.Align.START)
        content.pack_start(info_label, False, False, 0)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(name_box, False, False, 5)

        name_label = Gtk.Label(label="Название:")
        name_label.set_width_chars(12)
        name_label.set_halign(Gtk.Align.END)
        name_box.pack_start(name_label, False, False, 0)

        self._name_entry = Gtk.Entry()
        self._name_entry.set_placeholder_text("Название группы")
        if self._group:
            self._name_entry.set_text(self._group.name)
        name_box.pack_start(self._name_entry, True, True, 0)

        self._error_label = Gtk.Label()
        self._error_label.set_halign(Gtk.Align.START)
        self._error_label.set_line_wrap(True)
        content.pack_start(self._error_label, False, False, 5)

        content.show_all()

        self._name_entry.grab_focus()
        self._name_entry.select_region(0, -1)

    def get_group_name(self) -> str | None:
        """Get group name."""
        name = self._name_entry.get_text().strip()

        if not name:
            self._error_label.set_markup('<span color="red">[ERROR] Введите название группы</span>')
            return None

        return name


def show_edit_group_dialog(
    parent: Gtk.Window | None = None,
    group: ProfileGroup | None = None,
) -> str | None:
    """
    Show edit group dialog.

    Args:
        parent: Parent window
        group: Group to edit

    Returns:
        New group name if edited, None if cancelled
    """
    dialog = EditGroupDialog(parent, group)
    response = dialog.run()

    result = None
    if response == Gtk.ResponseType.OK:
        result = dialog.get_group_name()

    dialog.destroy()
    return result
