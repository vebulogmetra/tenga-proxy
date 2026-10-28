"""Общий каркас диалогов Qt: форма с кнопками, выбор по ключу, автосохранение.

Проверка полей — в `src/ui/logic/forms.py` и `settings_form.py`, общих с GTK;
здесь только то, что нужно виджетам Qt.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_WIDTH = 520
AUTOSAVE_DELAY_MS = 500

# Свои правила только для ошибок: поле в обычном состоянии остаётся системным.
FORM_STYLE = """
QLabel[error="true"] { color: #d13438; }
QLineEdit[error="true"], QPlainTextEdit[error="true"] { border: 1px solid #d13438; }
"""


def mark_error(widget: QWidget, message: str | None) -> None:
    """Подсветить поле с ошибкой и объяснить её во всплывающей подсказке."""
    widget.setProperty("error", bool(message))
    widget.setToolTip(message or "")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def icon_button(theme_icon: str, text: str, tooltip: str) -> QToolButton:
    """Кнопка с системной иконкой (`QIcon.ThemeIcon`), без неё — с подписью.

    На Windows иконки даёт шрифт Segoe Fluent Icons (Segoe MDL2 на 10), на
    Linux — тема рабочего стола; где темы нет, остаётся короткий текст.
    """
    button = QToolButton()
    icon = QIcon.fromTheme(getattr(QIcon.ThemeIcon, theme_icon))
    if icon.isNull():
        button.setText(text)
    else:
        button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    return button


def row(*widgets: QWidget) -> QWidget:
    """Поле с кнопками справа — одна строка формы."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == 0 else 0)
    return box


def clipboard_text() -> str:
    return QGuiApplication.clipboard().text().strip()


def copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class FormDialog(QDialog):
    """Модальная форма: поля, строка состояния, «Отмена» и кнопка подтверждения.

    Кнопка подтверждения — кнопка по умолчанию: Enter в последнем поле
    отправляет форму, как в обычных диалогах Windows.
    """

    def __init__(self, title: str, confirm_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(DEFAULT_WIDTH)
        self.setStyleSheet(FORM_STYLE)

        self.form = QFormLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        # Текст приходит из ссылок и от провайдеров: не разметка.
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.hide()

        self.buttons = QDialogButtonBox()
        self.confirm_button = self.buttons.addButton(
            confirm_label, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.confirm_button.setDefault(True)
        self.cancel_button = self.buttons.addButton(
            "Отмена", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.buttons.accepted.connect(self._on_confirm)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.status)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

    def set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _on_confirm(self) -> None:
        """Для наследников; по умолчанию просто закрывает форму."""
        self.accept()


class KeyedCombo(QComboBox):
    """Выпадающий список, адресуемый строковыми ключами настроек."""

    def __init__(self, keys: Iterable[str], labels: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.keys = list(keys)
        for key in self.keys:
            self.addItem(labels.get(key, key), key)

    def select(self, key: str) -> None:
        """Выбрать ключ; незнакомый (настройка другой версии) — первый."""
        index = self.findData(key)
        self.setCurrentIndex(index if index >= 0 else 0)

    def selected(self) -> str:
        key = self.currentData()
        return key if key is not None else self.keys[0]


class Debounce(QObject):
    """Отложенный вызов: серия правок сохраняется один раз, через полсекунды."""

    def __init__(
        self, fn: Callable[[], object], delay_ms: int = AUTOSAVE_DELAY_MS, parent=None
    ) -> None:
        super().__init__(parent)
        self._fn = fn
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(fn)

    def queue(self, *_args: object) -> None:
        self._timer.start()

    @property
    def pending(self) -> bool:
        return self._timer.isActive()

    def flush(self) -> None:
        """Сохранить отложенное сейчас: окно закрывается."""
        if self._timer.isActive():
            self._timer.stop()
            self._fn()


def watch(widgets: Iterable[QWidget], callback: Callable[..., object]) -> None:
    """Подписать callback на изменение каждого поля формы."""
    for widget in widgets:
        if isinstance(widget, QLineEdit | QPlainTextEdit):
            widget.textChanged.connect(callback)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(callback)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(callback)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(callback)
        else:
            raise TypeError(f"Неизвестное поле формы: {type(widget).__name__}")
