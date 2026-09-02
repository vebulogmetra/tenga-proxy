"""Add or edit a subscription (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.ui.dialogs4.base import FormDialog, read_clipboard
from src.ui.logic.forms import validate_subscription
from src.ui.logic.subscriptions_view import format_updated


class SubscriptionDialog(FormDialog):
    """Asks for the name and the address of a subscription."""

    __gtype_name__ = "TengaSubscriptionDialog"

    __gsignals__ = {
        "subscription-ready": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, group=None) -> None:
        title = "Редактировать подписку" if group is not None else "Добавить подписку"
        super().__init__(title, "Сохранить")
        self._group = group

        form = Adw.PreferencesGroup(title="Подписка")
        self.page.add(form)

        self.name_row = Adw.EntryRow(title="Название")
        self.name_row.connect("changed", self._on_changed)
        form.add(self.name_row)

        self.url_row = Adw.EntryRow(title="Адрес")
        paste = Gtk.Button(icon_name="edit-paste-symbolic", valign=Gtk.Align.CENTER)
        paste.add_css_class("flat")
        paste.set_tooltip_text("Вставить из буфера обмена")
        paste.connect("clicked", lambda _b: read_clipboard(self.url_row.set_text))
        self.url_row.add_suffix(paste)
        self.url_row.connect("changed", self._on_changed)
        form.add(self.url_row)

        # Строка создаётся всегда и прячется для новой подписки: так её не
        # приходится доставлять в разметку задним числом при первом обновлении.
        self.updated_row = Adw.ActionRow(title="Обновлено")
        self.updated_row.set_subtitle(format_updated(getattr(group, "last_updated", 0)))
        self.updated_row.set_visible(group is not None)
        form.add(self.updated_row)

        self.status_label = Gtk.Label(xalign=0.0, wrap=True)
        self.status_label.add_css_class("caption")
        self.status_label.set_margin_top(6)
        form.add(self.status_label)

        self.save_button = self.confirm_button
        if group is not None:
            self.name_row.set_text(group.name)
            self.url_row.set_text(group.subscription_url)
        self._on_changed(None)

    def _on_changed(self, _row) -> None:
        result = validate_subscription(self.name_row.get_text(), self.url_row.get_text())
        self.save_button.set_sensitive(result.ok)

        # Пустая форма только что открыта — сообщать об ошибке рано.
        blank = not self.name_row.get_text().strip() and not self.url_row.get_text().strip()
        self.status_label.set_text("" if result.ok or blank else result.message)
        if result.ok or blank:
            self.status_label.remove_css_class("error")
        else:
            self.status_label.add_css_class("error")

    def _on_confirm(self, _button: Gtk.Button) -> None:
        data = self.get_data()
        if data is None:
            return
        self.emit("subscription-ready", data[0], data[1])
        self.close()

    def get_data(self) -> tuple[str, str] | None:
        """Return the trimmed (name, url) pair, or None when invalid."""
        result = validate_subscription(self.name_row.get_text(), self.url_row.get_text())
        return result.value if result.ok else None
