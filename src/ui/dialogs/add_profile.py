"""Add a profile from a share link (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk, Pango

from src.ui.dialogs.base import FormDialog, read_clipboard
from src.ui.logic.forms import validate_profile_link

PLACEHOLDER = "vless://… trojan://… hysteria2://…"


class AddProfileDialog(FormDialog):
    """Asks for a share link and reports the parsed profile."""

    __gtype_name__ = "TengaAddProfileDialog"

    __gsignals__ = {
        "profile-ready": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self) -> None:
        super().__init__("Добавить профиль", "Добавить")
        self._bean = None
        # Имя, введённое вручную, не должно затираться именем из ссылки.
        self._name_touched = False

        group = Adw.PreferencesGroup()
        group.set_title("Ссылка подключения")
        self.page.add(group)

        self.link_row = Adw.EntryRow(title="Ссылка")
        self.link_row.set_show_apply_button(False)
        paste = Gtk.Button(icon_name="edit-paste-symbolic", valign=Gtk.Align.CENTER)
        paste.add_css_class("flat")
        paste.set_tooltip_text("Вставить из буфера обмена")
        paste.connect("clicked", self._on_paste)
        self.link_row.add_suffix(paste)
        self.link_row.connect("changed", self._on_link_changed)
        group.add(self.link_row)

        self.name_row = Adw.EntryRow(title="Имя")
        self.name_row.connect("changed", self._on_name_changed)
        group.add(self.name_row)

        # Подсказка внутри группы: отдельная метка под карточкой читалась бы
        # как подпись ко всей странице, а не к введённой ссылке.
        self.status_row = Adw.ActionRow()
        self.status_row.set_visible(False)
        self.status_row.add_css_class("property")
        group.add(self.status_row)
        self.status_label = Gtk.Label(xalign=0.0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.add_css_class("caption")
        self.status_row.add_prefix(self.status_label)

        self.add_button = self.confirm_button
        self.add_button.set_sensitive(False)

    # --- реакции ---

    def _on_name_changed(self, _row: Adw.EntryRow) -> None:
        if self.name_row.get_text().strip():
            self._name_touched = True

    def _on_link_changed(self, _row: Adw.EntryRow) -> None:
        text = self.link_row.get_text().strip()
        if not text:
            self._bean = None
            self._set_status("")
            self.add_button.set_sensitive(False)
            return

        result = validate_profile_link(text, name=self.name_row.get_text())
        self._bean = result.bean
        self._set_status(result.message, error=not result.ok)
        self.add_button.set_sensitive(result.ok)

        if result.ok and not self._name_touched and result.bean.name:
            # Флаг снимается вокруг подстановки: set_text снова эмитирует
            # changed, и без этого автозаполнение считалось бы ручным вводом.
            self.name_row.set_text(result.bean.name)
            self._name_touched = False

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status_label.set_text(text)
        self.status_row.set_visible(bool(text))
        if error:
            self.status_label.add_css_class("error")
        else:
            self.status_label.remove_css_class("error")

    def _on_paste(self, _button: Gtk.Button) -> None:
        read_clipboard(self.link_row.set_text)

    def _on_confirm(self, _button: Gtk.Button) -> None:
        bean = self.get_profile()
        if bean is None:
            return
        self.emit("profile-ready", bean)
        self.close()

    # --- результат ---

    def get_profile(self):
        """Return the parsed bean, with the typed name applied."""
        result = validate_profile_link(self.link_row.get_text(), name=self.name_row.get_text())
        return result.bean if result.ok else None
