"""Edit the basic parameters of a profile (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.ui.dialogs4.base import FormDialog, copy_to_clipboard
from src.ui.logic.forms import validate_profile_link

APPLIED = "Параметры обновлены из ссылки"


class EditProfileDialog(FormDialog):
    """Name, address, port and the share link of one profile."""

    __gtype_name__ = "TengaEditProfileDialog"

    __gsignals__ = {
        "profile-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, profile) -> None:
        super().__init__("Редактировать профиль", "Сохранить")
        self._profile = profile
        # Bean из применённой ссылки ждёт подтверждения: диалог правит живой
        # объект хранилища, и подмена сразу пережила бы Отмену.
        self._pending_bean = None

        bean = profile.bean

        main = Adw.PreferencesGroup(title="Основное")
        self.page.add(main)

        self.name_row = Adw.EntryRow(title="Имя")
        self.name_row.set_text(bean.display_name)
        main.add(self.name_row)

        self.address_row = Adw.EntryRow(title="Сервер")
        self.address_row.set_text(str(bean.server_address))
        main.add(self.address_row)

        self.port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.port_row.set_title("Порт")
        self.port_row.set_value(float(bean.server_port))
        main.add(self.port_row)

        link_group = Adw.PreferencesGroup(
            title="Строка подключения",
            description="Вставьте новую строку, чтобы заменить параметры профиля",
        )
        self.page.add(link_group)

        self.link_row = Adw.EntryRow(title="Ссылка")
        self.link_row.set_text(bean.to_share_link())

        copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
        copy.add_css_class("flat")
        copy.set_tooltip_text("Копировать")
        copy.connect("clicked", self._on_copy)
        self.link_row.add_suffix(copy)

        apply_button = Gtk.Button(label="Применить", valign=Gtk.Align.CENTER)
        apply_button.add_css_class("flat")
        apply_button.set_tooltip_text("Разобрать строку и обновить поля")
        apply_button.connect("clicked", lambda _b: self.apply_link())
        self.link_row.add_suffix(apply_button)

        link_group.add(self.link_row)

        self.status_label = Gtk.Label(xalign=0.0, wrap=True)
        self.status_label.add_css_class("caption")
        self.status_label.set_margin_top(6)
        link_group.add(self.status_label)

        self.save_button = self.confirm_button

    # --- действия ---

    def _on_copy(self, _button: Gtk.Button) -> None:
        copy_to_clipboard(self.link_row.get_text())
        self.status_label.remove_css_class("error")
        self.status_label.set_text("Ссылка скопирована")

    def apply_link(self) -> bool:
        """Parse the edited link and refresh the fields from it."""
        result = validate_profile_link(self.link_row.get_text())
        if not result.ok:
            self.status_label.add_css_class("error")
            self.status_label.set_text(result.message)
            return False

        bean = result.bean
        self._pending_bean = bean
        self.name_row.set_text(bean.display_name)
        self.address_row.set_text(str(bean.server_address))
        self.port_row.set_value(float(bean.server_port))
        self.link_row.set_text(bean.to_share_link())

        self.status_label.remove_css_class("error")
        self.status_label.set_text(APPLIED)
        return True

    def apply_changes(self) -> None:
        """Write the form back into the profile."""
        if self._pending_bean is not None:
            self._profile.bean = self._pending_bean
            self._pending_bean = None

        bean = self._profile.bean
        bean.name = self.name_row.get_text().strip()

        address = self.address_row.get_text().strip()
        if address:
            # Пустой адрес оставил бы профиль неработоспособным без единого
            # предупреждения — тогда лучше сохранить прежний.
            bean.server_address = address

        bean.server_port = int(self.port_row.get_value())

    def _on_confirm(self, _button: Gtk.Button) -> None:
        self.apply_changes()
        self.emit("profile-saved")
        self.close()
