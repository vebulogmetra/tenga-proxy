"""Прогресс проверки внутри строки группы, без виджетов на каждую строку."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
)

from src.ui.qt.models import GROUP, KIND_ROLE, PROGRESS_ROLE

PROGRESS_HEIGHT = 10
EXTRA_HEIGHT = 20


class ProfileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        if index.data(KIND_ROLE) == GROUP and index.data(PROGRESS_ROLE) is not None:
            size.setHeight(size.height() + EXTRA_HEIGHT)
        return size

    def paint(self, painter, option, index) -> None:
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
