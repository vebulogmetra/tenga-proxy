"""Добавление профиля по ссылке и правка его основных полей."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QSpinBox, QWidget

from src.ui.logic.forms import validate_profile_link
from src.ui.qt.dialogs.base import FormDialog, clipboard_text, copy_text, icon_button, row

PLACEHOLDER = "vless://… trojan://… hysteria2://…"
APPLIED = "Параметры обновлены из ссылки"


class AddProfileDialog(FormDialog):
    """Ссылка подключения и необязательное имя; сообщает разобранный профиль."""

    profile_ready = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, link: str = "") -> None:
        super().__init__("Добавить профиль", "Добавить", parent)
        # Имя, введённое вручную, не затирается именем из ссылки.
        self._name_touched = False

        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText(PLACEHOLDER)
        self.link_edit.textChanged.connect(self._on_link_changed)
        self.paste_button = icon_button("EditPaste", "Вставить", "Вставить из буфера обмена")
        self.paste_button.clicked.connect(lambda: self.link_edit.setText(clipboard_text()))
        self.form.addRow("Ссылка", row(self.link_edit, self.paste_button))

        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.form.addRow("Имя", self.name_edit)

        self.confirm_button.setEnabled(False)
        if link:
            self.link_edit.setText(link)

    def _on_name_edited(self, text: str) -> None:
        # textEdited, а не textChanged: подстановка имени из ссылки ручным
        # вводом не считается.
        self._name_touched = bool(text.strip())

    def _on_link_changed(self, text: str) -> None:
        if not text.strip():
            self.set_status("")
            self.confirm_button.setEnabled(False)
            return
        result = validate_profile_link(text, name=self.name_edit.text())
        self.set_status("\n".join((result.message, *result.warnings)), error=not result.ok)
        self.confirm_button.setEnabled(result.ok)
        if result.ok and not self._name_touched and result.bean.name:
            self.name_edit.setText(result.bean.name)

    def get_profile(self):
        """Разобранный профиль с введённым именем; None — ссылка не разбирается."""
        result = validate_profile_link(self.link_edit.text(), name=self.name_edit.text())
        return result.bean if result.ok else None

    def _on_confirm(self) -> None:
        bean = self.get_profile()
        if bean is None:
            return
        self.profile_ready.emit(bean)
        self.accept()


class EditProfileDialog(FormDialog):
    """Имя, сервер, порт и строка подключения одного профиля."""

    profile_saved = Signal()

    def __init__(self, profile, parent: QWidget | None = None) -> None:
        super().__init__("Редактировать профиль", "Сохранить", parent)
        self._profile = profile
        # Профиль из применённой ссылки ждёт «Сохранить»: форма правит живой
        # объект хранилища, и подмена сразу пережила бы «Отмену».
        self._pending_bean = None
        bean = profile.bean

        self.name_edit = QLineEdit(bean.display_name)
        self.form.addRow("Имя", self.name_edit)
        self.address_edit = QLineEdit(str(bean.server_address))
        self.form.addRow("Сервер", self.address_edit)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(bean.server_port))
        self.form.addRow("Порт", self.port_spin)

        self.link_edit = QLineEdit(bean.to_share_link())
        self.copy_button = icon_button("EditCopy", "Копировать", "Копировать ссылку")
        self.copy_button.clicked.connect(self._on_copy)
        self.apply_button = QPushButton("Применить")
        self.apply_button.setToolTip("Разобрать строку и обновить поля")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply_link)
        self.form.addRow("Ссылка", row(self.link_edit, self.copy_button, self.apply_button))
        hint = QLabel("Вставьте новую строку, чтобы заменить параметры профиля")
        hint.setWordWrap(True)
        self.form.addRow("", hint)

    def _on_copy(self) -> None:
        copy_text(self.link_edit.text())
        self.set_status("Ссылка скопирована")

    def apply_link(self) -> bool:
        """Разобрать строку и перенести её параметры в поля."""
        result = validate_profile_link(self.link_edit.text())
        if not result.ok:
            self.set_status(result.message, error=True)
            return False
        bean = result.bean
        self._pending_bean = bean
        self.name_edit.setText(bean.display_name)
        self.address_edit.setText(str(bean.server_address))
        self.port_spin.setValue(int(bean.server_port))
        self.link_edit.setText(bean.to_share_link())
        self.set_status("\n".join((APPLIED, *result.warnings)))
        return True

    def apply_changes(self) -> None:
        if self._pending_bean is not None:
            self._profile.bean = self._pending_bean
            self._pending_bean = None
        bean = self._profile.bean
        bean.name = self.name_edit.text().strip()
        address = self.address_edit.text().strip()
        if address:
            # Пустой адрес молча сломал бы профиль — тогда остаётся прежний.
            bean.server_address = address
        bean.server_port = self.port_spin.value()

    def _on_confirm(self) -> None:
        self.apply_changes()
        self.profile_saved.emit()
        self.accept()
