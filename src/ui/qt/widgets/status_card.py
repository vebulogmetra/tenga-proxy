"""Кликабельный монолит и пояснение его текущего действия."""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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

LOGO_SIZE = 108
FLAG_SIZE = 16


class ElidedLabel(QLabel):
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
    source = get_asset_path("icons/win/monolith.svg").read_bytes()
    color = {
        "status-disconnected": b"#8a969d",
        "status-error": b"#e07078",
        "status-connecting": b"#a9b8c4",
    }.get(css_class, b"#5ed3c7")
    if css_class != "status-connected":
        source = source.replace(b"#5ed3c7", color).replace(b"#a9ffe0", color)
    renderer = QSvgRenderer(source)
    pixmap = QPixmap(LOGO_SIZE * 4, LOGO_SIZE * 4)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(4)
    return pixmap


class StatusCard(QFrame):
    action_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.compact = False
        self.logo = QPushButton()
        self.logo.setAutoDefault(True)
        self.logo.setObjectName("monolithButton")
        self.logo.setFixedSize(120, 120)
        self.logo.clicked.connect(self.action_clicked)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setObjectName("statusTitle")
        self.flag = QLabel()
        self.flag.hide()
        self.subtitle = ElidedLabel()
        self.subtitle.setMinimumWidth(0)
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.metrics = QWidget()
        metrics_layout = QHBoxLayout(self.metrics)
        metrics_layout.setContentsMargins(0, 6, 0, 0)
        metrics_layout.setSpacing(24)
        self.metric_values = []
        for caption in ("Задержка", "↓ Получено", "↑ Отправлено"):
            item = QWidget()
            layout = QVBoxLayout(item)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            value = QLabel()
            value.setObjectName("metricValue")
            label = QLabel(caption)
            label.setObjectName("metricCaption")
            for text in (value, label):
                text.setAlignment(Qt.AlignmentFlag.AlignCenter)
                text.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(value)
            layout.addWidget(label)
            metrics_layout.addWidget(item)
            self.metric_values.append((item, value))
        self.mode = QLabel()
        self.mode.setObjectName("statusMode")
        self.health = QLabel()
        self.health.setObjectName("healthSummary")
        self.health.setWordWrap(True)
        self.health.setTextFormat(Qt.TextFormat.PlainText)
        self.instruction = QLabel()
        self.instruction.setObjectName("connectionInstruction")
        self.instruction.setWordWrap(True)
        self.instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_box = QWidget()
        self.text_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.text_box.installEventFilter(self)
        self._profile_name = ""
        texts = QVBoxLayout(self.text_box)
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(3)
        self.name_box = QWidget()
        name = QHBoxLayout(self.name_box)
        name.setContentsMargins(0, 0, 0, 0)
        name.setSpacing(6)
        name.addWidget(self.flag)
        name.addWidget(self.subtitle, 1)
        for label in (self.title, self.subtitle, self.mode):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        texts.addWidget(self.title)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        texts.addWidget(self.mode)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(20, 10, 20, 12)
        self.grid.setSpacing(6)
        self._arrange()

    def _fit_name(self) -> None:
        width = self.subtitle.fontMetrics().horizontalAdvance(self._profile_name) + 4
        if not self.flag.isHidden():
            width += FLAG_SIZE + 6
        available = self.text_box.width()
        if self.compact:
            available = min(available, (self.width() - self.logo.width() - 52) // 2)
        self.name_box.setFixedWidth(min(max(0, available), width))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.text_box and event.type() == QEvent.Type.Resize:
            self._fit_name()
        return super().eventFilter(watched, event)

    def set_compact(self, compact: bool) -> None:
        if compact != self.compact:
            self.compact = compact
            self._arrange()

    def _arrange(self) -> None:
        for widget in (self.logo, self.text_box, self.name_box, self.metrics, self.health):
            self.grid.removeWidget(widget)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if self.compact else 0)
        if self.compact:
            self.grid.setColumnStretch(1, 0)
            self.logo.setFixedSize(104, 104)
            self.grid.addWidget(self.name_box, 0, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.grid.addWidget(self.text_box, 1, 0)
            self.grid.addWidget(self.logo, 0, 1, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(self.metrics, 0, 2, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(self.health, 2, 0, 1, 3)
        else:
            self.logo.setFixedSize(120, 120)
            self.grid.addWidget(self.name_box, 0, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.grid.addWidget(self.logo, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(self.text_box, 2, 0)
            self.grid.addWidget(self.metrics, 3, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.grid.addWidget(self.health, 4, 0)
        self.logo.setIconSize(self.logo.size() * 0.9)
        self.health.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def update_view(self, view: StatusView, *, enabled: bool = True, mode: str = "") -> None:
        self.title.setText(view.title)
        icon, name = flagged(view.subtitle)
        self._profile_name = name
        self.flag.setVisible(icon is not None)
        if icon is not None:
            self.flag.setPixmap(icon.pixmap(FLAG_SIZE, FLAG_SIZE))
        self.subtitle.setText(name)
        self.subtitle.setToolTip(view.subtitle)
        self.name_box.setVisible(bool(view.subtitle))
        self.subtitle.setVisible(bool(view.subtitle))
        self._fit_name()
        values = dict(view.metric_items)
        for caption, (item, value) in zip(
            ("Задержка", "↓ Получено", "↑ Отправлено"), self.metric_values, strict=True
        ):
            value.setText(values.get(caption, ""))
            item.setVisible(caption in values)
        self.metrics.setVisible(bool(values))
        self.mode.setText(f"Режим {mode}" if mode else "")
        self.mode.setVisible(bool(mode))
        if view.css_class == "status-connecting":
            instruction = view.title
        elif not enabled:
            instruction = "Сначала добавьте или выберите сервер"
        elif view.css_class == "status-connected":
            instruction = "Нажмите на логотип для отключения"
        elif view.css_class == "status-error":
            instruction = "Нажмите на логотип для повторного подключения"
        else:
            instruction = "Нажмите на логотип для подключения"
        self.instruction.setText(instruction)
        self.instruction.hide()
        self.logo.setIcon(QIcon(logo_pixmap(view.css_class)))
        self.logo.setEnabled(enabled)
        self.logo.setAccessibleName(view.button_label)
        self.logo.setToolTip(instruction)
        self.setProperty("state", view.css_class)
        for widget in (self, self.title, self.logo):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
