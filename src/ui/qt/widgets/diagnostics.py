"""Журнал в панели мониторинга: последние записи, экспорт, очистка.

Текст собирает `read_diagnostics` (src/core/diagnostics_export.py), общий с
GTK: секреты замаскированы, размер ограничен. Чтение — в фоне, раз в две
секунды, пока панель видна.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.core.diagnostics_export import read_diagnostics
from src.ui.controller import CONFIRM_DELETE
from src.ui.logic.async_utils import run_in_background
from src.ui.qt.dialogs.confirm import build_confirmation

REFRESH_INTERVAL_MS = 2000
EXPORT_NAME = "veblock-diagnostics.txt"


def default_log_dir() -> Path:
    from src.core.config import LOG_DIR

    return LOG_DIR


def ask_export_path(parent: QWidget) -> str:
    path, _filter = QFileDialog.getSaveFileName(
        parent, "Экспорт очищенного журнала", EXPORT_NAME, "Текст (*.txt)"
    )
    return path


class DiagnosticsPanel(QGroupBox):
    def __init__(
        self,
        *,
        dispatch: Callable[..., object],
        show_dialog: Callable[[QWidget], object],
        log_dir: Callable[[], Path] = default_log_dir,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Журнал", parent)
        self.setToolTip("Последние записи. Хранение — 3 дня; секреты маскируются.")
        self._dispatch = dispatch
        self._show_dialog = show_dialog
        self._log_dir = log_dir
        self._busy = False
        self.ask_export_path = ask_export_path
        self.thread = None

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        # Строки журнала длинные: перенос растягивал бы панель на пол-экрана.
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        families = set(QFontDatabase.families())
        for family in ("Cascadia Mono", "Consolas"):
            if family in families:
                font = QFont(family, max(10, self.font().pointSize()))
                break
        self.view.setFont(font)
        self.view.setMinimumHeight(160)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Экспорт…")
        self.export_button.clicked.connect(self.export)
        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self.clear)

        buttons = QHBoxLayout()
        self.wrap_button = QCheckBox("Перенос строк")
        self.wrap_button.toggled.connect(
            lambda checked: self.view.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth
                if checked
                else QPlainTextEdit.LineWrapMode.NoWrap
            )
        )
        buttons.addWidget(self.wrap_button)
        buttons.addStretch(1)
        for button in (self.refresh_button, self.export_button, self.clear_button):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.set_active(True)

    def hideEvent(self, event) -> None:
        self.set_active(False)
        super().hideEvent(event)

    def _run(self, fn, on_done=None, on_error=None, *, name: str):
        def alive(callback):
            if callback is None:
                return None
            return lambda value: callback(value) if isValid(self) else None

        self.thread = run_in_background(
            fn, alive(on_done), alive(on_error), dispatch=self._dispatch, name=name
        )
        return self.thread

    def set_active(self, active: bool) -> None:
        """Читать журнал, только пока его видно."""
        if active and not self._timer.isActive():
            self.refresh()
            self._timer.start()
        elif not active:
            self._timer.stop()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def done(text: str) -> None:
            self._busy = False
            self.status.hide()
            # Прокрутка не прыгает вверх, если читатель смотрит конец журнала.
            bar = self.view.verticalScrollBar()
            at_end = bar.value() == bar.maximum()
            position = bar.value()
            horizontal = self.view.horizontalScrollBar().value()
            if text == self.view.toPlainText():
                return
            self.view.setPlainText(text)
            if at_end:
                bar.setValue(bar.maximum())
            else:
                bar.setValue(position)
            self.view.horizontalScrollBar().setValue(horizontal)

        def failed(_error) -> None:
            self._busy = False
            self.status.setText("Не удалось прочитать журнал. Повторите обновление.")
            self.status.show()

        self._run(lambda: read_diagnostics(self._log_dir()), done, failed, name="tenga-diag")

    def export(self) -> None:
        path = self.ask_export_path(self)
        if not path:
            return
        target = Path(path)

        def write() -> None:
            target.write_text(read_diagnostics(self._log_dir()), encoding="utf-8")

        self._run(
            write,
            on_error=lambda _error: self.view.setPlainText("Не удалось экспортировать журнал"),
            name="tenga-diag-export",
        )

    def clear(self) -> None:
        from src.core.log_manager import LogManager

        def confirmed() -> None:
            self._run(
                lambda: LogManager(self._log_dir()).clear_all_logs(),
                lambda _result: self.refresh(),
                name="tenga-diag-clear",
            )

        self._show_dialog(
            build_confirmation(
                CONFIRM_DELETE,
                "Очистить журналы?",
                "Все сохранённые записи будут удалены.",
                confirmed,
                confirm_label="Очистить",
                parent=self.window(),
            )
        )
