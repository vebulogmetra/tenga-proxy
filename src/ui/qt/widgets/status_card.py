"""Карточка состояния подключения: «Монолит», тексты и главная кнопка.

Всё, что показывается, приходит готовым `StatusView` из
`src/ui/logic/status.py` — тем же, что у GTK-карточки.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.config import get_asset_path
from src.ui.logic.status import StatusView
from src.ui.qt.icons import flagged

LOGO_SIZE = 48
FLAG_SIZE = 16


class ElidedLabel(QLabel):
    """Keep the full profile name available while fitting the status card."""

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        super().setText(
            self.fontMetrics().elidedText(
                getattr(self, "_full_text", ""), Qt.TextElideMode.ElideRight, self.width()
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()


@cache
def logo_pixmap(css_class: str) -> QPixmap:
    """«Монолит» с ядром цвета состояния: `status-connected` → monolith-connected.png."""
    state = css_class.removeprefix("status-")
    pixmap = QPixmap(str(get_asset_path(f"icons/win/monolith-{state}.png")))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        LOGO_SIZE,
        LOGO_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class StatusCard(QFrame):
    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.logo = QLabel()
        self.logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        self.title = QLabel()
        self.title.setObjectName("statusTitle")
        # Имя профиля с флагом картинкой: эмодзи-флагов в шрифтах Windows нет.
        self.flag = QLabel()
        self.flag.hide()
        self.subtitle = ElidedLabel()
        self.subtitle.setMinimumWidth(0)
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.metrics = QLabel()
        self.metrics.setWordWrap(True)
        self.metrics.setObjectName("statusMetrics")
        self.button = QPushButton()
        self.button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.button.setMinimumWidth(140)
        self.button.clicked.connect(self.action_clicked)

        name = QHBoxLayout()
        name.setSpacing(6)
        name.addWidget(self.flag)
        name.addWidget(self.subtitle, 1)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        for label in (self.title, self.subtitle, self.metrics):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texts.addWidget(self.title)
        texts.addLayout(name)
        texts.addWidget(self.metrics)
        text_box = QWidget()
        texts.setContentsMargins(0, 0, 0, 0)
        text_box.setLayout(texts)
        text_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._tools = QHBoxLayout()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)
        layout.addWidget(self.logo)
        layout.addWidget(text_box, 1)
        layout.addWidget(self.button)
        layout.addLayout(self._tools)

    def add_tool(self, widget: QWidget) -> None:
        """Кнопки окна (панель мониторинга, меню) справа от главной."""
        self._tools.addWidget(widget)

    def update_view(self, view: StatusView) -> None:
        self.title.setText(view.title)
        self.title.ensurePolished()
        self.title.setMinimumWidth(self.title.fontMetrics().horizontalAdvance(view.title) + 4)
        icon, name = flagged(view.subtitle)
        self.flag.setVisible(icon is not None)
        if icon is not None:
            self.flag.setPixmap(icon.pixmap(FLAG_SIZE, FLAG_SIZE))
        self.subtitle.setText(name)
        self.subtitle.setToolTip(view.subtitle)
        self.subtitle.setVisible(bool(view.subtitle))
        self.metrics.setText(view.metrics)
        self.metrics.setVisible(bool(view.metrics))
        self.button.setText(view.button_label)
        self.logo.setPixmap(logo_pixmap(view.css_class))
        # Свойства читает style.qss: цвет заголовка и вид кнопки по состоянию.
        self.setProperty("state", view.css_class)
        self.button.setProperty("role", view.button_class)
        for widget in (self, self.title, self.button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
