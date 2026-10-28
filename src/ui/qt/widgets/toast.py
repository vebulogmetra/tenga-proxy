"""Короткое сообщение внизу окна, с необязательной кнопкой действия."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

TOAST_TIMEOUT_MS = 4000


class Toast(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton()
        self.button.clicked.connect(self._on_button)
        layout = QHBoxLayout(self)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._on_click: Callable[[], None] | None = None
        self.hide()

    def show_message(
        self,
        text: str,
        *,
        button: str | None = None,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        """Новое сообщение заменяет прежнее: очередь тостов тут не нужна."""
        self.label.setText(text)
        self._on_click = on_click
        self.button.setText(button or "")
        self.button.setVisible(bool(button and on_click))
        self.show()
        self.raise_()
        self._timer.start(TOAST_TIMEOUT_MS)

    def _on_button(self) -> None:
        self.hide()
        if self._on_click is not None:
            self._on_click()
