"""Добавление и правка подписки."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from src.ui.logic.forms import validate_subscription
from src.ui.logic.subscriptions_view import format_updated
from src.ui.qt.dialogs.base import FormDialog, clipboard_text, icon_button, row


class SubscriptionDialog(FormDialog):
    """Название и адрес подписки; сообщает пару (название, адрес)."""

    subscription_ready = Signal(str, str)

    def __init__(self, group=None, parent: QWidget | None = None) -> None:
        title = "Редактировать подписку" if group is not None else "Добавить подписку"
        super().__init__(title, "Сохранить", parent)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("По адресу, если не указать")
        self.form.addRow("Название", self.name_edit)
        self.url_edit = QLineEdit()
        self.paste_button = icon_button("EditPaste", "Вставить", "Вставить из буфера обмена")
        self.paste_button.clicked.connect(lambda: self.url_edit.setText(clipboard_text()))
        self.form.addRow("Адрес", row(self.url_edit, self.paste_button))
        self.updated_label = QLabel(format_updated(getattr(group, "last_updated", 0)))
        if group is not None:
            self.form.addRow("Обновлено", self.updated_label)
            self.name_edit.setText(group.name)
            self.url_edit.setText(group.subscription_url)

        self.name_edit.textChanged.connect(self._on_changed)
        self.url_edit.textChanged.connect(self._on_changed)
        self._on_changed()

    def _on_changed(self, *_args) -> None:
        result = validate_subscription(self.name_edit.text(), self.url_edit.text())
        self.confirm_button.setEnabled(result.ok)
        # Пустая форма только что открыта — говорить об ошибке рано.
        blank = not self.name_edit.text().strip() and not self.url_edit.text().strip()
        self.set_status("" if result.ok or blank else result.message, error=True)

    def get_data(self) -> tuple[str, str] | None:
        result = validate_subscription(self.name_edit.text(), self.url_edit.text())
        return result.value if result.ok else None

    def _on_confirm(self) -> None:
        data = self.get_data()
        if data is None:
            return
        self.subscription_ready.emit(*data)
        self.accept()
