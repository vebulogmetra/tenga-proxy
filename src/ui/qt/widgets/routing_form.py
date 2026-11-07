"""Форма маршрутизации (Qt): та же, что в GTK `src/ui/widgets/routing_form.py`.

Одна форма — в настройках приложения (общие правила) и в диалоге сервера
(свои правила). Значения ходят через `src/ui/logic/routing_form.py`.
"""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.db.config import RoutingMode
from src.ui.logic.routing_form import (
    LISTS,
    ORDER_LABELS,
    ORDER_PRESETS,
    FormValues,
    apply_form_values,
    current_catalog,
    form_values,
    ru_direct_subtitle,
)
from src.ui.qt.dialogs.base import KeyedCombo, mark_error


def _check(text: str, subtitle: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(subtitle)
    return box


class RoutingForm(QWidget):
    """Группа «Режим» и четыре списка в одной колонке."""

    def __init__(self, *, vpn_hint: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._enabled = True
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)

        mode = QGroupBox("Режим")
        form = QFormLayout(mode)
        self.mode_combo = KeyedCombo(RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Правила", self.mode_combo)
        self.order_combo = KeyedCombo(ORDER_PRESETS, ORDER_LABELS)
        form.addRow("Приоритет групп", self.order_combo)
        self.bypass_check = _check(
            "Локальные сети напрямую",
            "127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
        )
        form.addRow(self.bypass_check)
        self.ru_direct_check = _check(
            "Российские сайты и IP напрямую", ru_direct_subtitle(current_catalog())
        )
        form.addRow(self.ru_direct_check)
        column.addWidget(mode)

        self.lists: dict[str, QPlainTextEdit] = {}
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for key, title, hint in LISTS:
            if key == "vpn" and vpn_hint is not None:
                hint = vpn_hint
            box = QGroupBox(title)
            box.setToolTip(hint)
            inner = QVBoxLayout(box)
            edit = QPlainTextEdit()
            edit.setFont(font)
            edit.setPlaceholderText(hint)
            edit.setMinimumHeight(110)
            inner.addWidget(edit)
            self.lists[key] = edit
            column.addWidget(box)

    # --- состояние ---

    def _sync_mode(self) -> None:
        # В режиме «всё через прокси» списки не применяются: активными они
        # обещали бы несуществующий эффект. «Локальные сети» действуют всегда.
        custom = self._enabled and self.mode_combo.selected() == RoutingMode.CUSTOM
        for widget in (*self.lists.values(), self.order_combo, self.ru_direct_check):
            widget.setEnabled(custom)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.mode_combo.setEnabled(enabled)
        self.bypass_check.setEnabled(enabled)
        self._sync_mode()

    def fields(self) -> list[QWidget]:
        return [
            self.mode_combo,
            self.order_combo,
            self.bypass_check,
            self.ru_direct_check,
            *self.lists.values(),
        ]

    def load(self, routing) -> None:
        values = form_values(routing)
        self.mode_combo.select(values.mode)
        self.order_combo.select(values.order)
        self.bypass_check.setChecked(values.bypass_local_networks)
        self.ru_direct_check.setChecked(values.ru_direct)
        for key, text in values.lists.items():
            self.lists[key].setPlainText(text)
            mark_error(self.lists[key], None)
        self._sync_mode()

    def values(self) -> FormValues:
        return FormValues(
            mode=self.mode_combo.selected(),
            order=self.order_combo.selected(),
            bypass_local_networks=self.bypass_check.isChecked(),
            ru_direct=self.ru_direct_check.isChecked(),
            lists={key: edit.toPlainText() for key, edit in self.lists.items()},
        )

    def read(self, routing) -> None:
        """Записать форму в `routing`; список с ошибкой подсвечен, ValueError наружу."""
        from src.ui.logic.forms import parse_host_list

        first_error: ValueError | None = None
        for edit in self.lists.values():
            try:
                parse_host_list(edit.toPlainText())
                mark_error(edit, None)
            except ValueError as error:
                mark_error(edit, str(error))
                first_error = first_error or error
        if first_error is not None:
            raise first_error
        apply_form_values(routing, self.values())
