"""Create or rename a group (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.ui.dialogs4.base import FormDialog
from src.ui.logic.forms import validate_group_name


def _title_for(group) -> str:
    if group is None:
        return "Новая группа"
    if getattr(group, "is_subscription", False):
        return "Редактировать подписку"
    return "Редактировать группу"


class GroupDialog(FormDialog):
    """Asks for a group name."""

    __gtype_name__ = "TengaGroupDialog"

    __gsignals__ = {
        "group-ready": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, group=None) -> None:
        super().__init__(_title_for(group), "Сохранить")
        self._group = group
        self.set_content_height(260)

        form = Adw.PreferencesGroup()
        self.page.add(form)

        self.name_row = Adw.EntryRow(title="Название")
        self.name_row.connect("changed", self._on_changed)
        form.add(self.name_row)

        self.save_button = self.confirm_button
        if group is not None:
            self.name_row.set_text(group.name)
        self._on_changed(None)

    def _on_changed(self, _row) -> None:
        self.save_button.set_sensitive(validate_group_name(self.name_row.get_text()).ok)

    def _on_confirm(self, _button: Gtk.Button) -> None:
        name = self.get_name()
        if name is None:
            return
        self.emit("group-ready", name)
        self.close()

    def get_name(self) -> str | None:
        """Return the trimmed name, or None when blank."""
        result = validate_group_name(self.name_row.get_text())
        return result.value if result.ok else None
