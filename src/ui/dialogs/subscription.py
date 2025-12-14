from __future__ import annotations
from typing import TYPE_CHECKING
import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from src.db.profiles import ProfileGroup


class SubscriptionDialog(Gtk.Dialog):
    """Dialog for adding/editing subscription."""

    def __init__(
        self,
        parent: Gtk.Window | None = None,
        group: ProfileGroup | None = None,
    ):
        super().__init__(
            title="Добавить подписку" if group is None else "Редактировать",
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

        self.set_default_size(600, 300)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)

        self._group = group
        self._name_entry: Gtk.Entry | None = None
        self._url_entry: Gtk.Entry | None = None
        self._error_label: Gtk.Label | None = None
        self._last_updated_label: Gtk.Label | None = None

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
        info_label.set_markup("<b>Настройки подписки</b>")
        info_label.set_halign(Gtk.Align.START)
        content.pack_start(info_label, False, False, 0)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(name_box, False, False, 5)

        name_label = Gtk.Label(label="Название:")
        name_label.set_width_chars(12)
        name_label.set_halign(Gtk.Align.END)
        name_box.pack_start(name_label, False, False, 0)

        self._name_entry = Gtk.Entry()
        self._name_entry.set_placeholder_text("Название подписки")
        if self._group:
            self._name_entry.set_text(self._group.name)
        name_box.pack_start(self._name_entry, True, True, 0)

        url_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(url_box, False, False, 5)

        url_label = Gtk.Label(label="URL подписки:")
        url_label.set_width_chars(12)
        url_label.set_halign(Gtk.Align.END)
        url_box.pack_start(url_label, False, False, 0)

        self._url_entry = Gtk.Entry()
        self._url_entry.set_placeholder_text("https://...")
        if self._group:
            self._url_entry.set_text(self._group.subscription_url)
        self._url_entry.connect("changed", self._on_url_changed)
        url_box.pack_start(self._url_entry, True, True, 0)

        paste_button = Gtk.Button(label="📋")
        paste_button.set_tooltip_text("Вставить из буфера обмена")
        paste_button.connect("clicked", self._on_paste_clicked)
        url_box.pack_start(paste_button, False, False, 0)

        if self._group and self._group.last_updated > 0:
            last_updated_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            content.pack_start(last_updated_box, False, False, 5)

            last_updated_title = Gtk.Label(label="Обновлено:")
            last_updated_title.set_width_chars(12)
            last_updated_title.set_halign(Gtk.Align.END)
            last_updated_box.pack_start(last_updated_title, False, False, 0)

            self._last_updated_label = Gtk.Label()
            self._update_last_updated_label()
            last_updated_box.pack_start(self._last_updated_label, True, True, 0)

        self._error_label = Gtk.Label()
        self._error_label.set_halign(Gtk.Align.START)
        self._error_label.set_line_wrap(True)
        content.pack_start(self._error_label, False, False, 5)

        content.show_all()

        if not self._group:
            self._url_entry.grab_focus()
        else:
            self._name_entry.grab_focus()

    def _update_last_updated_label(self) -> None:
        """Update last updated label."""
        if not self._group or not self._last_updated_label:
            return

        if self._group.last_updated > 0:
            import datetime

            update_time = datetime.datetime.fromtimestamp(self._group.last_updated)
            time_str = update_time.strftime("%d.%m.%Y %H:%M:%S")
            self._last_updated_label.set_text(time_str)
        else:
            self._last_updated_label.set_text("Никогда")

    def _on_url_changed(self, entry: Gtk.Entry) -> None:
        """Handle URL change."""
        url = entry.get_text().strip()

        if not url:
            self._error_label.set_text("")
            return

        if url.startswith(("http://", "https://")):
            self._error_label.set_markup('<span color="green">[OK] URL валиден</span>')
        else:
            self._error_label.set_markup(
                '<span color="orange">[WARN] URL должен начинаться с http:// или https://</span>'
            )

    def _on_paste_clicked(self, button: Gtk.Button) -> None:
        """Paste from clipboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if text:
            self._url_entry.set_text(text.strip())

    def get_subscription_data(self) -> tuple[str, str] | None:
        """Get subscription name and URL."""
        name = self._name_entry.get_text().strip()
        url = self._url_entry.get_text().strip()

        if not name:
            self._error_label.set_markup('<span color="red">[ERROR] Введите название подписки</span>')
            return None

        if not url:
            self._error_label.set_markup('<span color="red">[ERROR] Введите URL подписки</span>')
            return None

        if not url.startswith(("http://", "https://")):
            self._error_label.set_markup(
                '<span color="red">[ERROR] URL должен начинаться с http:// или https://</span>'
            )
            return None

        return (name, url)


def show_subscription_dialog(
    parent: Gtk.Window | None = None,
    group: ProfileGroup | None = None,
) -> tuple[str, str] | None:
    """
    Show subscription dialog.

    Args:
        parent: Parent window
        group: Existing group to edit (None for new)

    Returns:
        Tuple of (name, url) if subscription added, None if cancelled
    """
    dialog = SubscriptionDialog(parent, group)
    response = dialog.run()

    result = None
    if response == Gtk.ResponseType.OK:
        result = dialog.get_subscription_data()

    dialog.destroy()
    return result
