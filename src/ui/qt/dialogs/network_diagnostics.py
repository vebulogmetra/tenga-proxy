"""Окно «Диагностика сети» (Qt): рисует `DiagnosticsView`, логики здесь нет."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.diag.export import export_filename
from src.ui.logic.diagnostics_session import DiagnosticsSession
from src.ui.logic.diagnostics_view import (
    ALREADY_RUNNING,
    CAUSES_RUNNING,
    CONSENT,
    COPIED,
    COPY,
    EXPORT,
    EXPORT_FAILED,
    EXPORTED,
    IDLE_BODY,
    IDLE_TITLE,
    PREVIOUS,
    RETRY,
    RUNNING_TITLE,
    SUMMARY_TITLE,
    TITLE,
    Card,
    Chip,
    DiagnosticsView,
    Group,
    Row,
    Tone,
    ViewUpdater,
    summary_text,
)
from src.ui.qt.dialogs.base import copy_text

_TONE_SIGNS = {Tone.GOOD: "✓", Tone.BAD: "✕", Tone.NEUTRAL: "ⓘ"}
_TONE_COLORS = {Tone.GOOD: "#2e9d58", Tone.BAD: "#d13438", Tone.NEUTRAL: ""}


def _label(text: str, *, muted: bool = False, heading: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if muted:
        # Не setEnabled(False): выключенный текст бледнее нужного и не выделяется.
        label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    if heading:
        font = label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        label.setFont(font)
    return label


def _chip(chip: Chip) -> QLabel:
    label = QLabel(chip.text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    color = _TONE_COLORS[chip.tone]
    style = "font-weight: 600;"
    if color:
        style += f" color: {color};"
    label.setStyleSheet(style)
    return label


def _row(row: Row) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 2, 0, 2)
    sign = QLabel(_TONE_SIGNS[row.tone])
    color = _TONE_COLORS[row.tone]
    if color:
        sign.setStyleSheet(f"color: {color};")
    layout.addWidget(sign, 0, Qt.AlignmentFlag.AlignTop)
    texts = QVBoxLayout()
    texts.addWidget(_label(row.title))
    if row.subtitle:
        texts.addWidget(_label(row.subtitle, muted=True))
    layout.addLayout(texts, 1)
    if row.value:
        layout.addWidget(_label(row.value, muted=True), 0, Qt.AlignmentFlag.AlignTop)
    return widget


class NetworkDiagnosticsWindow(QDialog):
    def __init__(
        self,
        session: DiagnosticsSession,
        loop,
        *,
        on_recommendation: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(TITLE)
        self.resize(720, 820)
        self._session = session
        self._on_recommendation = on_recommendation
        self._expanded: set[tuple[str, str]] = set()
        self.last_toast_for_test = ""

        layout = QVBoxLayout(self)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self._scroll, 1)
        self._message = QLabel()
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.setWordWrap(True)
        self._message.hide()
        layout.addWidget(self._message)
        self.primary_button = QPushButton()
        self.primary_button.setDefault(False)
        self.primary_button.setAutoDefault(False)
        self.primary_button.clicked.connect(self._on_primary)
        layout.addWidget(self.primary_button)

        self.finished.connect(lambda _result: self._on_finished())
        self._updater = ViewUpdater(session, loop, self._render)
        self._updater.attach()

    @property
    def view(self) -> DiagnosticsView | None:
        return self._updater.view

    def toast(self, text: str) -> None:
        self.last_toast_for_test = text
        self._message.setText(text)
        self._message.show()

    def keyPressEvent(self, event) -> None:
        # Случайный Esc не должен молча останавливать проверку на три минуты.
        if event.key() != Qt.Key.Key_Escape:
            super().keyPressEvent(event)

    # Команды

    def _on_finished(self) -> None:
        self._updater.detach()
        self._session.close()

    def _on_primary(self) -> None:
        if self._session.running:
            self._session.stop()
        else:
            self._session.start()

    def _on_retry(self, section) -> None:
        if not self._session.start(section):
            self.toast(ALREADY_RUNNING)

    def on_copy(self) -> None:
        text = summary_text(self._session)
        if text is not None:
            copy_text(text)
            self.toast(COPIED)

    def on_export(self) -> None:
        report = self._session.report
        if report is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, EXPORT, export_filename(report), "JSON (*.json)"
        )
        if path:
            self.save_report(path)

    def save_report(self, path: str) -> None:
        self.toast(EXPORTED if self._session.export(path) else EXPORT_FAILED)

    # Отрисовка

    def _render(self, view: DiagnosticsView) -> None:
        self.primary_button.setText(view.primary_label)
        self._message.hide()
        bar = self._scroll.verticalScrollBar()
        position = bar.value()
        self._scroll.setWidget(self._build(view))
        bar.setValue(position)

    def _build(self, view: DiagnosticsView) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        if view.idle:
            layout.addWidget(_label(IDLE_TITLE, heading=True))
            layout.addWidget(_label(IDLE_BODY, muted=True))
        else:
            layout.addWidget(self._summary(view))
        if view.error:
            layout.addWidget(_chip(Chip(view.error, Tone.BAD)))
        for card in view.cards:
            layout.addWidget(self._card(card))
        if view.technical is not None:
            layout.addWidget(self._card(view.technical))
        for note in view.footnotes:
            layout.addWidget(_label(note, muted=True))
        if view.idle:
            layout.addWidget(_label(CONSENT, muted=True))
        methodology = Group(
            "Что и как проверяется", "Методика, ограничения и приватность", view.methodology
        )
        layout.addWidget(self._expander(Card("Методика"), methodology))
        layout.addStretch(1)
        return page

    def _summary(self, view: DiagnosticsView) -> QWidget:
        box = QGroupBox(SUMMARY_TITLE)
        layout = QVBoxLayout(box)
        if view.network:
            line = QHBoxLayout()
            line.addWidget(_label(view.network), 1)
            for chip in view.chips:
                line.addWidget(_chip(chip))
            layout.addLayout(line)
        if view.scope:
            layout.addWidget(_label(view.scope))
        if view.warning:
            layout.addWidget(_chip(Chip(view.warning, Tone.BAD)))
        if view.progress_text is not None:
            layout.addWidget(_label(RUNNING_TITLE, heading=True))
            layout.addWidget(self._busy())
            layout.addWidget(_label(view.progress_text, muted=True))
        if view.verdict is not None:
            layout.addWidget(_label(view.verdict, heading=True))
        for note in view.verdict_notes:
            layout.addWidget(_label(note))
        for title, chip in view.state_rows:
            line = QHBoxLayout()
            line.addWidget(_label(title), 1)
            line.addWidget(_chip(chip))
            layout.addLayout(line)
        if view.causes_running:
            layout.addWidget(_label(CAUSES_RUNNING))
            layout.addWidget(self._busy())
        elif view.causes_text:
            layout.addWidget(_label(view.causes_text))
        buttons = QHBoxLayout()
        for action in view.actions:
            button = QPushButton(action.label)
            button.setAutoDefault(False)
            button.clicked.connect(
                lambda _checked=False, code=action.code: self._on_recommendation(code)
            )
            buttons.addWidget(button)
        if view.can_copy:
            copy = QPushButton(COPY)
            copy.setAutoDefault(False)
            copy.clicked.connect(self.on_copy)
            buttons.addWidget(copy)
        if view.can_export:
            export = QPushButton(EXPORT)
            export.setAutoDefault(False)
            export.clicked.connect(self.on_export)
            buttons.addWidget(export)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    @staticmethod
    def _busy() -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        return bar

    def _card(self, card: Card) -> QWidget:
        box = QGroupBox(card.title)
        layout = QVBoxLayout(box)
        header = QHBoxLayout()
        if card.previous:
            header.addWidget(_chip(Chip(PREVIOUS)))
        if card.chip is not None:
            header.addWidget(_chip(card.chip))
        header.addStretch(1)
        if card.section is not None:
            retry = QPushButton(RETRY)
            retry.setAutoDefault(False)
            retry.setEnabled(card.retry_enabled)
            retry.clicked.connect(lambda _checked=False, s=card.section: self._on_retry(s))
            header.addWidget(retry)
        layout.addLayout(header)
        for line in card.lines:
            layout.addWidget(_label(line))
        if card.progress is not None:
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(card.progress * 1000))
            bar.setTextVisible(False)
            layout.addWidget(bar)
        for item in card.groups:
            if item.expanded:
                for row in item.rows:
                    layout.addWidget(_row(row))
            else:
                layout.addWidget(self._expander(card, item))
        for note in card.notes:
            layout.addWidget(_label(note, muted=True))
        return box

    def _expander(self, card: Card, item: Group) -> QWidget:
        key = (card.title, item.title)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QToolButton()
        header.setCheckable(True)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setArrowType(Qt.ArrowType.RightArrow)
        header.setText(item.title)
        header.setAutoRaise(True)
        layout.addWidget(header)
        if item.summary:
            layout.addWidget(_label(item.summary, muted=True))
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(16, 0, 0, 0)
        body.hide()
        layout.addWidget(body)
        filled = {"done": False}

        def on_toggled(checked: bool) -> None:
            header.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            if checked:
                self._expanded.add(key)
                # Строки создаются при раскрытии: технических наблюдений бывают сотни.
                if not filled["done"]:
                    filled["done"] = True
                    for row in item.rows:
                        rows.addWidget(_row(row))
            else:
                self._expanded.discard(key)
            body.setVisible(checked)

        header.toggled.connect(on_toggled)
        if key in self._expanded:
            header.setChecked(True)
        return widget
