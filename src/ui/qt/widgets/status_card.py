"""Кликабельный монолит и пояснение его текущего действия."""

from __future__ import annotations

from functools import lru_cache

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
from src.ui.logic.appearance import GLOW_COLORS, STATE_COLORS, glow_color
from src.ui.logic.status import StatusView, action_hint
from src.ui.qt.icons import flagged

LOGO_SIZE = 260
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


@lru_cache(maxsize=64)
def logo_pixmap(css_class: str, size: int = LOGO_SIZE, dpr: float = 1.0) -> QPixmap:
    source = get_asset_path("icons/win/monolith.svg").read_bytes()
    # Отключение рисует монолит серым без гало; пустое хранилище — бирюзовым без гало.
    fallback = STATE_COLORS[css_class] if css_class == "status-disconnected" else None
    color = (glow_color(css_class) or fallback or GLOW_COLORS["status-connected"]).encode()
    if css_class != "status-connected":
        source = source.replace(b"#5ed3c7", color).replace(b"#a9ffe0", color)
    if css_class in ("status-disconnected", "status-empty"):
        source = source.replace(b'stop-opacity=".48"', b'stop-opacity="0"')
    renderer = QSvgRenderer(source)
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
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
        metrics_layout.setSpacing(16)
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
            label.setWordWrap(False)
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
        self.state_dot = QLabel("●")
        self.state_dot.setObjectName("connectionDot")
        status_row = QHBoxLayout()
        status_row.addStretch()
        status_row.addWidget(self.state_dot)
        status_row.addWidget(self.title)
        status_row.addStretch()
        texts.addLayout(status_row)
        self.server_caption = QLabel("Активный сервер")
        self.server_caption.setObjectName("serverCaption")
        self.server_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(20, 10, 20, 12)
        self.grid.setSpacing(6)
        self._arrange()

    def _fit_name(self) -> None:
        width = self.subtitle.fontMetrics().horizontalAdvance(self._profile_name) + 4
        if not self.flag.isHidden():
            width += FLAG_SIZE + 6
        available = self.text_box.width()
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
        for widget in (
            self.logo,
            self.instruction,
            self.text_box,
            self.server_caption,
            self.name_box,
            self.mode,
            self.metrics,
            self.health,
        ):
            self.grid.removeWidget(widget)
        size = 152 if self.compact else 280
        self.instruction.setStyleSheet("font-size: 9pt;" if self.compact else "")
        self.title.setStyleSheet("font-size: 17pt; padding: 4px 0;" if self.compact else "")
        self.server_caption.setStyleSheet("padding-top: 2px;" if self.compact else "")
        self.mode.setStyleSheet("padding: 5px 0;" if self.compact else "")
        self.health.setStyleSheet("padding: 6px 0;" if self.compact else "")
        for item, value in self.metric_values:
            value.setStyleSheet("font-size: 12pt;" if self.compact else "")
            item.layout().itemAt(1).widget().setStyleSheet(
                "font-size: 9pt;" if self.compact else ""
            )
        self.logo.setFixedSize(size, size)
        self.logo.setIconSize(self.logo.size() * 0.94)
        for row, widget in enumerate(
            (
                self.logo,
                self.instruction,
                self.text_box,
                self.server_caption,
                self.name_box,
                self.mode,
                self.metrics,
                self.health,
            )
        ):
            if widget in (self.logo, self.name_box, self.metrics):
                self.grid.addWidget(widget, row, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
            else:
                self.grid.addWidget(widget, row, 0)
        self.metrics.layout().setSpacing(8 if self.compact else 16)
        self.setProperty("compact", self.compact)
        self.grid.setRowStretch(7, 1)
        self.grid.addWidget(self.health, 8, 0)
        self._update_icon()
        self.grid.setColumnStretch(0, 1)
        self.health.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_icon(self) -> None:
        key = (
            getattr(self, "_icon_state", "status-disconnected"),
            self.logo.iconSize().width(),
            self.devicePixelRatioF(),
        )
        if key != getattr(self, "_icon_key", None):
            pixmap = logo_pixmap(*key)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Mode.Disabled)
            self.logo.setIcon(icon)
            self._icon_key = key

    def update_view(self, view: StatusView) -> None:
        self.title.setText(view.title)
        icon, name = flagged(view.subtitle)
        self._profile_name = name
        self.flag.setVisible(icon is not None)
        if icon is not None:
            self.flag.setPixmap(icon.pixmap(FLAG_SIZE, FLAG_SIZE))
        self.subtitle.setText(name)
        self.subtitle.setToolTip(view.subtitle)
        self.name_box.setVisible(bool(view.subtitle))
        self.server_caption.setText(
            "Активный сервер" if view.css_class == "status-connected" else "Сервер"
        )
        self.server_caption.setVisible(bool(view.subtitle))
        self.subtitle.setVisible(bool(view.subtitle))
        self._fit_name()
        values = dict(view.metric_items)
        for caption, (item, value) in zip(
            ("Задержка", "↓ Получено", "↑ Отправлено"), self.metric_values, strict=True
        ):
            value.setText(values.get(caption, ""))
            item.setVisible(caption in values)
        self.metrics.setVisible(bool(values))
        self.mode.setText(view.mode)
        self.mode.setVisible(bool(view.mode))
        instruction = action_hint(view)
        self.instruction.setText(instruction)
        self.instruction.show()
        self._icon_state = view.css_class
        self._update_icon()
        self.logo.setEnabled(view.action_enabled)
        self.logo.setAccessibleName(view.button_label)
        self.logo.setToolTip(instruction)
        self.setProperty("state", view.css_class)
        for widget in (self, self.title, self.logo, self.state_dot):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
