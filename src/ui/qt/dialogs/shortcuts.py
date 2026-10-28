"""Сочетания клавиш: таблица действий и справка по ним."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Те же сочетания, что в GTK (`_ACCELS` в src/ui/application.py).
SHORTCUTS: dict[str, str] = {
    "add-profile": "Ctrl+N",
    "add-subscription": "Ctrl+Shift+N",
    "settings": "Ctrl+,",
    "refresh-subscriptions": "F5",
    "quit": "Ctrl+Q",
    "hide-window": "Ctrl+W",
    "toggle-connection": "Ctrl+Return",
    "test-latency": "Ctrl+T",
    "search": "Ctrl+F",
}

# Порядок справки смысловой, как в GTK-справке (src/ui/shortcuts.py).
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Соединение",
        [
            ("toggle-connection", "Подключить или отключить"),
            ("test-latency", "Проверить задержку"),
        ],
    ),
    (
        "Профили и подписки",
        [
            ("add-profile", "Добавить профиль"),
            ("add-subscription", "Добавить подписку"),
            ("refresh-subscriptions", "Обновить подписки"),
            ("search", "Поиск"),
        ],
    ),
    (
        "Приложение",
        [
            ("settings", "Настройки"),
            ("hide-window", "Скрыть окно"),
            ("quit", "Выход"),
        ],
    ),
]


def native_text(action: str) -> str:
    """Сочетание так, как его пишет система: на macOS — значками, иначе Ctrl+…"""
    return QKeySequence(SHORTCUTS[action]).toString(QKeySequence.SequenceFormat.NativeText)


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сочетания клавиш")
        self.setModal(True)
        layout = QVBoxLayout(self)
        for title, entries in SECTIONS:
            box = QGroupBox(title)
            form = QFormLayout(box)
            for action, description in entries:
                form.addRow(description, QLabel(native_text(action)))
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
