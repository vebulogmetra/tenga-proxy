"""Подтверждение импорта общей маршрутизации ссылкой."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.routing_import import ImportRow

BODY = (
    "Текущие списки будут заменены. Вернуть их можно в настройках: «О программе» → «Обслуживание»."
)
WARNING_COLOR = QColor("#d13438")


class RoutingImportDialog(QDialog):
    """Строки «подпись — значение» с раскрываемыми изменениями списков."""

    def __init__(
        self,
        rows: list[ImportRow],
        on_confirm: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт маршрутизации")
        self.setModal(True)
        self.setMinimumWidth(560)

        body = QLabel(BODY)
        body.setWordWrap(True)

        # Значения приходят из ссылки: только текст, без разметки (у
        # QTreeWidgetItem её и нет).
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(any(row.details for row in rows))
        for row in rows:
            item = QTreeWidgetItem([row.label, row.value])
            item.setToolTip(1, row.value)
            for line in row.details:
                item.addChild(QTreeWidgetItem(["", line]))
            if row.warning:
                for column in (0, 1):
                    item.setForeground(column, QBrush(WARNING_COLOR))
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton(
            "Импортировать", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        # Импорт обратим откатом, но по умолчанию — всё равно «Отмена».
        self.cancel_button.setDefault(True)
        self.import_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.accepted.connect(on_confirm)

        layout = QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)

    def row_titles(self) -> list[str]:
        return [self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())]
