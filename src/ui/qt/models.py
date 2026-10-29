"""Модель дерева серверов над `build_profile_rows()`.

Строки собирает `src/ui/logic/profiles_view.py`, как и для GTK: отбор,
сортировка и порядок групп проверяются без Qt. Модель только раскладывает
готовые `GroupRow`/`ProfileRow` по ячейкам.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel

from src.ui.logic.latency import PingProgress
from src.ui.logic.profiles_view import GroupRow, ProfileRow, SortKey, ping_text
from src.ui.qt.icons import flagged

COLUMNS = ("Имя", "Тип", "Сервер", "Пинг")
NAME_COLUMN, TYPE_COLUMN, ADDRESS_COLUMN, PING_COLUMN = range(len(COLUMNS))

# По «Серверу» не сортируют и в GTK: колонки нет в SortKey.
SORT_KEYS = {NAME_COLUMN: SortKey.NAME, TYPE_COLUMN: SortKey.TYPE, PING_COLUMN: SortKey.PING}

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
ID_ROLE = Qt.ItemDataRole.UserRole + 2
DETAILS_ROLE = Qt.ItemDataRole.UserRole + 3
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 4
GROUP, PROFILE = "group", "profile"

# Истёкшая подписка: тот же красный, что у ошибок в карточке.
EXPIRED_COLOR = QColor("#d13438")


def _cell(text: str) -> QStandardItem:
    item = QStandardItem(text)
    item.setEditable(False)
    return item


def group_count_text(row: GroupRow, progress: PingProgress | None) -> str:
    """Число профилей, а во время замера группы — «готово / всего»."""
    state = progress.state(row.group_id) if progress is not None else None
    if state is None:
        return str(row.count)
    done, total = state
    return f"{done} / {total}"


def group_summary(row: GroupRow, progress: PingProgress | None, details: str) -> str:
    summary = f"{row.title}  ·  Профилей: {row.count}"
    if progress is not None and progress.state(row.group_id) is not None:
        summary += f"  ·  Проверено: {group_count_text(row, progress)}"
    return f"{summary}  ·  {details}" if details else summary


class ProfileTreeModel(QStandardItemModel):
    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self._rows: list[GroupRow] = []

    def set_rows(
        self,
        rows: list[GroupRow],
        progress: PingProgress | None = None,
        details: Mapping[int, tuple[str, bool]] | None = None,
    ) -> None:
        """`details` — трафик и срок подписки по id группы: (текст, истекла ли)."""
        self._rows = rows
        self.removeRows(0, self.rowCount())
        for row in rows:
            text, expired = (details or {}).get(row.group_id, ("", False))
            self.appendRow(self._group_items(row, progress, text, expired))

    def _group_items(
        self, row: GroupRow, progress: PingProgress | None, details: str, expired: bool
    ) -> list[QStandardItem]:
        summary = group_summary(row, progress, details)
        name = _cell(summary)
        name.setToolTip(summary)
        name.setData(details, DETAILS_ROLE)
        name.setData(progress.state(row.group_id) if progress is not None else None, PROGRESS_ROLE)
        if expired:
            name.setForeground(QBrush(EXPIRED_COLOR))
        cells = [name, _cell(""), _cell(""), _cell("")]
        for cell in cells:
            cell.setData(GROUP, KIND_ROLE)
            cell.setData(row.group_id, ID_ROLE)
        font = QFont(name.font())
        font.setBold(True)
        name.setFont(font)
        for child in row.children:
            name.appendRow(self._profile_items(child))
        return cells

    def _profile_items(self, row: ProfileRow) -> list[QStandardItem]:
        icon, title = flagged(row.title)
        name = _cell(title)
        if row.is_active:
            name.setText(f"{title}  ·  Подключён")
        name.setToolTip(row.title)
        if icon is not None:
            name.setIcon(icon)
        cells = [
            name,
            _cell(row.proxy_type.upper()),
            _cell(row.address),
            _cell(ping_text(row.latency_ms)),
        ]
        cells[ADDRESS_COLUMN].setToolTip(row.address)
        cells[PING_COLUMN].setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        for cell in cells:
            cell.setData(PROFILE, KIND_ROLE)
            cell.setData(row.profile_id, ID_ROLE)
            if row.is_active:
                font = QFont(cell.font())
                font.setBold(True)
                cell.setFont(font)
        return cells

    def update_group_progress(self, group_id: int, progress: PingProgress | None) -> None:
        index = self.group_index(group_id)
        row = next((r for r in self._rows if r.group_id == group_id), None)
        if not index.isValid() or row is None:
            return
        item = self.item(index.row(), NAME_COLUMN)
        summary = group_summary(row, progress, item.data(DETAILS_ROLE) or "")
        item.setText(summary)
        item.setToolTip(summary)
        item.setData(progress.state(group_id) if progress is not None else None, PROGRESS_ROLE)

    def group_index(self, group_id: int) -> QModelIndex:
        for position in range(self.rowCount()):
            item = self.item(position, NAME_COLUMN)
            if item.data(ID_ROLE) == group_id:
                return item.index()
        return QModelIndex()

    def profile_index(self, profile_id: int) -> QModelIndex:
        for position in range(self.rowCount()):
            group = self.item(position, NAME_COLUMN)
            for child in range(group.rowCount()):
                item = group.child(child, NAME_COLUMN)
                if item.data(ID_ROLE) == profile_id:
                    return item.index()
        return QModelIndex()

    @staticmethod
    def target(index: QModelIndex) -> tuple[str, int] | None:
        """(«group» или «profile», id) строки под индексом."""
        if not index.isValid():
            return None
        return index.data(KIND_ROLE), index.data(ID_ROLE)
