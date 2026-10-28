"""Создание и переименование группы."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from src.ui.logic.forms import validate_group_name
from src.ui.qt.dialogs.base import FormDialog


def title_for(group) -> str:
    if group is None:
        return "Новая группа"
    if getattr(group, "is_subscription", False):
        return "Редактировать подписку"
    return "Редактировать группу"


class GroupDialog(FormDialog):
    group_ready = Signal(str)

    def __init__(self, group=None, parent: QWidget | None = None) -> None:
        super().__init__(title_for(group), "Сохранить", parent)
        self.name_edit = QLineEdit(group.name if group is not None else "")
        self.name_edit.textChanged.connect(self._on_changed)
        self.form.addRow("Название", self.name_edit)
        self._on_changed()

    def _on_changed(self, *_args) -> None:
        self.confirm_button.setEnabled(validate_group_name(self.name_edit.text()).ok)

    def get_name(self) -> str | None:
        result = validate_group_name(self.name_edit.text())
        return result.value if result.ok else None

    def _on_confirm(self) -> None:
        name = self.get_name()
        if name is None:
            return
        self.group_ready.emit(name)
        self.accept()
