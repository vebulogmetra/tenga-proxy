from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GLib, Gtk

if TYPE_CHECKING:
    from src.db.profiles import ProfileEntry


class EditProfileDialog(Gtk.Dialog):
    """Dialog for editing basic profile parameters."""

    def __init__(self, profile: ProfileEntry, parent: Gtk.Window | None = None):
        super().__init__(
            title="Редактировать профиль",
            transient_for=parent,
            flags=0,
        )

        self.set_wmclass("tenga-proxy", "tenga-proxy")
        self.set_role("tenga-proxy")
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.connect("realize", self._on_realize)

        self._profile = profile

        self.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK,
            Gtk.ResponseType.OK,
        )

        self.set_default_size(500, 200)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_taskbar_hint(True)

        self._name_entry: Gtk.Entry | None = None
        self._address_entry: Gtk.Entry | None = None
        self._port_entry: Gtk.SpinButton | None = None
        self._conn_string_entry: Gtk.Entry | None = None
        self._copy_button: Gtk.Button | None = None

        self._setup_ui()

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Handle window realization - set WM_CLASS via Gdk.Window."""
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

        bean = self._profile.bean

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(name_box, False, False, 5)

        name_label = Gtk.Label(label="Имя:")
        name_label.set_width_chars(10)
        name_label.set_halign(Gtk.Align.END)
        name_box.pack_start(name_label, False, False, 0)

        self._name_entry = Gtk.Entry()
        self._name_entry.set_text(bean.display_name)
        name_box.pack_start(self._name_entry, True, True, 0)

        addr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(addr_box, False, False, 5)

        addr_label = Gtk.Label(label="Сервер:")
        addr_label.set_width_chars(10)
        addr_label.set_halign(Gtk.Align.END)
        addr_box.pack_start(addr_label, False, False, 0)

        self._address_entry = Gtk.Entry()
        self._address_entry.set_text(str(bean.server_address))
        addr_box.pack_start(self._address_entry, True, True, 0)

        port_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(port_box, False, False, 5)

        port_label = Gtk.Label(label="Порт:")
        port_label.set_width_chars(10)
        port_label.set_halign(Gtk.Align.END)
        port_box.pack_start(port_label, False, False, 0)

        adjustment = Gtk.Adjustment(
            value=float(bean.server_port),
            lower=1.0,
            upper=65535.0,
            step_increment=1.0,
            page_increment=10.0,
        )
        self._port_entry = Gtk.SpinButton()
        self._port_entry.set_adjustment(adjustment)
        self._port_entry.set_numeric(True)
        port_box.pack_start(self._port_entry, False, False, 0)

        # Add connection string display with copy button
        conn_string_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(conn_string_box, False, False, 5)

        conn_string_label = Gtk.Label(label="Ссылка:")
        conn_string_label.set_width_chars(10)
        conn_string_label.set_halign(Gtk.Align.END)
        conn_string_box.pack_start(conn_string_label, False, False, 0)

        self._conn_string_entry = Gtk.Entry()
        self._conn_string_entry.set_text(bean.to_share_link())
        self._conn_string_entry.set_editable(False)  # Make it read-only
        conn_string_box.pack_start(self._conn_string_entry, True, True, 0)

        self._copy_button = Gtk.Button(label="Копировать")
        self._copy_button.connect("clicked", self._on_copy_clicked)
        conn_string_box.pack_start(self._copy_button, False, False, 0)

        content.show_all()

    def _on_copy_clicked(self, button: Gtk.Button) -> None:
        """Handle copy button click."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        conn_string = self._profile.bean.to_share_link()
        clipboard.set_text(conn_string, -1)

        # Show a brief notification that the link was copied
        self._copy_button.set_label("Скопировано!")
        GLib.timeout_add(1000, self._reset_copy_button_label)  # Reset after 1 second

    def _reset_copy_button_label(self) -> bool:
        """Reset the copy button label after a delay."""
        self._copy_button.set_label("Копировать")
        return False  # Return False to stop the timeout

    def apply_changes(self) -> None:
        """Apply changes to profile."""
        bean = self._profile.bean

        if self._name_entry is not None:
            name = self._name_entry.get_text().strip()
            bean.name = name

        if self._address_entry is not None:
            address = self._address_entry.get_text().strip()
            if address:
                bean.server_address = address

        if self._port_entry is not None:
            port = int(self._port_entry.get_value())
            bean.server_port = port


def show_edit_profile_dialog(
    profile: ProfileEntry,
    parent: Gtk.Window | None = None,
) -> bool:
    """
    Show edit profile dialog.

    Returns:
        True if changes applied, False if cancelled.
    """
    dialog = EditProfileDialog(profile, parent)
    response = dialog.run()

    changed = False
    if response == Gtk.ResponseType.OK:
        dialog.apply_changes()
        changed = True

    dialog.destroy()
    return changed
