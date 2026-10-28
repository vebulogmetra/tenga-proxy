"""Подтверждения: удаление, смена адреса подписки, очистка журналов."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from src.ui.controller import CONFIRM_URL_CHANGE


def build_confirmation(
    kind: str,
    heading: str,
    body: str,
    on_confirm: Callable[[], None],
    *,
    confirm_label: str | None = None,
    parent: QWidget | None = None,
) -> QMessageBox:
    """Вопрос с двумя кнопками; показ — за вызывающим (слот диалога приложения)."""
    if kind == CONFIRM_URL_CHANGE:
        accept, reject = "Сменить", "Оставить"
    else:
        accept, reject = confirm_label or "Удалить", "Отмена"
    box = QMessageBox(QMessageBox.Icon.Question, heading, body, parent=parent)
    # Текст не разметка: имена и адреса приходят от провайдера.
    box.setTextFormat(Qt.TextFormat.PlainText)
    accept_button = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton(reject, QMessageBox.ButtonRole.RejectRole)
    # Enter и Escape не подтверждают: удалить или сменить можно только явно.
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)

    def finished(_result: int) -> None:
        if box.clickedButton() is accept_button:
            on_confirm()

    box.finished.connect(finished)
    return box
