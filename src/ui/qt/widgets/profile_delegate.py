"""Прогресс проверки внутри строки группы, без виджетов на каждую строку."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
)

from src.ui.logic.appearance import ACCENT
from src.ui.qt.models import (
    ACTIVE_ROLE,
    ADDRESS_COLUMN,
    GROUP,
    KIND_ROLE,
    PING_COLUMN,
    PROFILE,
    PROGRESS_ROLE,
    TYPE_COLUMN,
)

PROGRESS_HEIGHT = 10
EXTRA_HEIGHT = 20


class ProfileDelegate(QStyledItemDelegate):
    menu_requested = Signal(object, object)
    ping_requested = Signal(object)

    @staticmethod
    def ping_button_rect(rect: QRect) -> QRect:
        return QRect(rect.right() - 100, rect.bottom() - 29, 68, 24)

    def editorEvent(self, event, model, option, index) -> bool:
        if (
            index.column() == 0
            and index.data(KIND_ROLE) == PROFILE
            and (
                event.type()
                in (
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonRelease,
                    QEvent.Type.MouseButtonDblClick,
                )
                and event.button() == Qt.MouseButton.LeftButton
                and self.ping_button_rect(option.rect).contains(event.position().toPoint())
            )
        ):
            if event.type() == QEvent.Type.MouseButtonRelease:
                self.ping_requested.emit(index)
            return True
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and event.position().x() >= option.rect.right() - 32
        ):
            self.menu_requested.emit(index, event.position().toPoint())
            return True
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        if index.data(KIND_ROLE) == PROFILE:
            size.setHeight(max(size.height(), 64))
        if index.data(KIND_ROLE) == GROUP and index.data(PROGRESS_ROLE) is not None:
            size.setHeight(size.height() + EXTRA_HEIGHT)
        return size

    def paint(self, painter, option, index) -> None:
        if index.data(KIND_ROLE) == PROFILE and index.column() == 0:
            painter.save()
            item = QStyleOptionViewItem(option)
            self.initStyleOption(item, index)
            item.text = ""
            item.icon = QIcon()
            style = option.widget.style() if option.widget else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, item, painter, option.widget)
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            active = bool(index.data(ACTIVE_ROLE))
            background = option.palette.base().color()
            tint = option.palette.highlight().color() if selected else QColor(ACCENT)
            if selected or active:
                amount = 0.15 if selected else 0.08
                background = QColor.fromRgbF(
                    background.redF() * (1 - amount) + tint.redF() * amount,
                    background.greenF() * (1 - amount) + tint.greenF() * amount,
                    background.blueF() * (1 - amount) + tint.blueF() * amount,
                )
            painter.fillRect(option.rect, background)
            if selected:
                painter.setPen(option.palette.highlight().color())
                painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 6, 6)
            painter.setPen(option.palette.text().color())
            rect = option.rect.adjusted(12, 8, -12, -8)
            title = str(index.data() or "").removesuffix("  ·  Подключён")
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon is not None and not icon.isNull():
                icon.paint(painter, QRect(rect.left(), rect.top() + 2, 16, 16))
                rect.adjust(24, 0, 0, 0)
            font = item.font
            font.setBold(True)
            painter.setFont(font)
            if active:
                painter.fillRect(
                    QRect(option.rect.left(), option.rect.top() + 8, 3, option.rect.height() - 16),
                    QColor(ACCENT),
                )
            text = QFontMetrics(font).elidedText(
                title, Qt.TextElideMode.ElideRight, max(0, rect.width() - 220)
            )
            painter.drawText(rect, Qt.AlignmentFlag.AlignTop, text)
            painter.setFont(option.font)
            detail = " · ".join(
                str(index.siblingAtColumn(c).data() or "") for c in (TYPE_COLUMN, ADDRESS_COLUMN)
            )
            painter.setPen(option.palette.placeholderText().color())
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignBottom,
                option.fontMetrics.elidedText(
                    detail, Qt.TextElideMode.ElideRight, max(0, rect.width() - 220)
                ),
            )
            right = rect.adjusted(0, 0, -24, 0)
            painter.drawText(
                right,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                str(index.siblingAtColumn(PING_COLUMN).data() or ""),
            )
            if active:
                painter.setPen(QColor(ACCENT))
                painter.drawText(
                    right.adjusted(0, 0, -76, 0),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                    "Подключён",
                )
            button_rect = self.ping_button_rect(option.rect)
            painter.setBrush(option.palette.button())
            painter.setPen(option.palette.mid().color())
            painter.drawRoundedRect(button_rect.adjusted(0, 0, -1, -1), 5, 5)
            painter.setPen(option.palette.buttonText().color())
            painter.drawText(button_rect, Qt.AlignmentFlag.AlignCenter, "Пинг")
            painter.setPen(option.palette.text().color())
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "⋮")
            painter.restore()
            return
        progress = index.data(PROGRESS_ROLE)
        if index.data(KIND_ROLE) != GROUP or progress is None:
            super().paint(painter, option, index)
            return
        title = QStyleOptionViewItem(option)
        title.rect.setHeight(max(0, option.rect.height() - EXTRA_HEIGHT))
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(
            option.rect, option.palette.highlight() if selected else option.palette.base()
        )
        super().paint(painter, title, index)
        done, total = progress
        bar = QStyleOptionProgressBar()
        bar.rect = QRect(
            option.rect.left() + 8,
            title.rect.bottom() + 5,
            max(0, option.rect.width() - 16),
            PROGRESS_HEIGHT,
        )
        bar.minimum = 0
        bar.maximum = max(1, total)
        bar.progress = min(done, total)
        bar.palette = option.palette
        bar.state = option.state | QStyle.StateFlag.State_Horizontal
        bar.textVisible = False
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget)
        painter.restore()
