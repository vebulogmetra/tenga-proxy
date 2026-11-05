"""Окно «Диагностика сети» (GTK4): рисует `DiagnosticsView`, логики здесь нет."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango

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

_TONE_ICONS = {
    Tone.GOOD: "emblem-ok-symbolic",
    Tone.BAD: "window-close-symbolic",
    Tone.NEUTRAL: "dialog-information-symbolic",
}
_TONE_CLASSES = {Tone.GOOD: "success", Tone.BAD: "error", Tone.NEUTRAL: "dim-label"}


def _label(text: str, *classes: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0, wrap=True, use_markup=False, selectable=True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)  # длинные имена хостов не растягивают окно
    for name in classes:
        label.add_css_class(name)
    return label


def _chip(chip: Chip) -> Gtk.Label:
    label = Gtk.Label(label=chip.text, wrap=True, use_markup=False, valign=Gtk.Align.CENTER)
    # Иначе короткая подпись переносится по словам ещё до нехватки места.
    label.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
    label.add_css_class("caption-heading")
    label.add_css_class(_TONE_CLASSES[chip.tone])
    return label


def _section(title: str, suffix: Gtk.Widget | None = None) -> Gtk.Box:
    """Заголовок и столбец. Не `PreferencesGroup`: тот ставит строки выше остального текста."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    header = Gtk.Box(spacing=12)
    heading = Gtk.Label(label=title, xalign=0, hexpand=True, use_markup=False)
    heading.add_css_class("heading")
    header.append(heading)
    if suffix is not None:
        header.append(suffix)
    box.append(header)
    return box


def _list() -> Gtk.ListBox:
    rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    rows.add_css_class("boxed-list")
    return rows


def _row(row: Row) -> Adw.ActionRow:
    # Подпись тона обязательна: цвет и значок сами по себе не читаются вслух.
    widget = Adw.ActionRow(title=row.title, subtitle=row.subtitle)
    widget.set_use_markup(False)
    widget.set_title_lines(0)
    widget.set_subtitle_lines(0)
    icon = Gtk.Image.new_from_icon_name(_TONE_ICONS[row.tone])
    icon.add_css_class(_TONE_CLASSES[row.tone])
    widget.add_prefix(icon)
    if row.value:
        value = Gtk.Label(label=row.value, use_markup=False, wrap=True, xalign=1)
        value.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
        value.add_css_class("dim-label")
        widget.add_suffix(value)
    return widget


class NetworkDiagnosticsWindow(Adw.Window):
    __gtype_name__ = "TengaNetworkDiagnosticsWindow"

    def __init__(
        self,
        session: DiagnosticsSession,
        loop,
        *,
        on_recommendation: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(title=TITLE, default_width=720, default_height=820, **kwargs)
        self._session = session
        self._on_recommendation = on_recommendation
        self._expanded: set[tuple[str, str]] = set()
        self.export_dialog_requested = False

        self._toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        self._scroller = Gtk.ScrolledWindow(vexpand=True)
        self._clamp = Adw.Clamp(maximum_size=680)
        self._scroller.set_child(self._clamp)
        toolbar.set_content(self._scroller)

        bottom = Gtk.Box(margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.primary_button = Gtk.Button(hexpand=True)
        self.primary_button.add_css_class("pill")
        self.primary_button.connect("clicked", self._on_primary)
        bottom.append(self.primary_button)
        toolbar.add_bottom_bar(bottom)

        self._toasts.set_child(toolbar)
        self.set_content(self._toasts)

        self.connect("close-request", self._on_close)
        self._updater = ViewUpdater(session, loop, self._render)
        self._updater.attach()

    @property
    def view(self) -> DiagnosticsView | None:
        return self._updater.view

    def toast(self, text: str) -> None:
        self.last_toast_for_test = text
        self._toasts.add_toast(Adw.Toast(title=text))

    # Команды

    def _on_close(self, _window) -> bool:
        self._updater.detach()
        self._session.close()
        return False

    def _on_primary(self, _button) -> None:
        if self._session.running:
            self._session.stop()
        else:
            self._session.start()

    def _on_retry(self, section) -> None:
        if not self._session.start(section):
            self.toast(ALREADY_RUNNING)

    def on_copy(self, _button=None) -> None:
        text = summary_text(self._session)
        if text is None:
            return
        self.get_clipboard().set(text)
        self.toast(COPIED)

    def on_export(self, _button=None) -> None:
        report = self._session.report
        if report is None:
            return
        self.export_dialog_requested = True
        dialog = Gtk.FileDialog(initial_name=export_filename(report), title=EXPORT)
        dialog.save(self, None, self._on_export_chosen)

    def _on_export_chosen(self, dialog, result) -> None:
        try:
            chosen = dialog.save_finish(result)
        except GLib.Error:
            return  # Пользователь отменил выбор файла.
        path = chosen.get_path() if chosen is not None else None
        if path is not None:
            self.save_report(path)

    def save_report(self, path: str) -> None:
        self.toast(EXPORTED if self._session.export(path) else EXPORT_FAILED)

    # Отрисовка

    def _render(self, view: DiagnosticsView) -> None:
        self.primary_button.set_label(view.primary_label)
        if view.running:
            self.primary_button.remove_css_class("suggested-action")
        else:
            self.primary_button.add_css_class("suggested-action")
        # Содержимое заменяется целиком: положение прокрутки возвращается после разметки.
        adjustment = self._scroller.get_vadjustment()
        position = adjustment.get_value()
        self._clamp.set_child(self._build(view))
        GLib.idle_add(self._restore_scroll, adjustment, position)

    @staticmethod
    def _restore_scroll(adjustment, position) -> bool:
        adjustment.set_value(position)
        return GLib.SOURCE_REMOVE

    def _build(self, view: DiagnosticsView) -> Gtk.Widget:
        page = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=18,
            margin_bottom=18,
            margin_start=12,
            margin_end=12,
        )
        if view.idle:
            page.append(_label(IDLE_TITLE, "title-2"))
            page.append(_label(IDLE_BODY, "dim-label"))
        else:
            page.append(self._summary(view))
        if view.error:
            page.append(_label(view.error, "error"))
        for card in view.cards:
            page.append(self._card(card))
        if view.technical is not None:
            page.append(self._card(view.technical))
        for note in view.footnotes:
            page.append(_label(note, "caption", "dim-label"))
        if view.idle:
            page.append(_label(CONSENT, "caption", "dim-label"))
        page.append(self._methodology(view))
        return page

    def _summary(self, view: DiagnosticsView) -> Gtk.Widget:
        box = _section(SUMMARY_TITLE)
        if view.network:
            line = Gtk.Box(spacing=12)
            line.append(_label(view.network))
            for chip in view.chips:
                line.append(_chip(chip))
            box.append(line)
        if view.scope:
            box.append(_label(view.scope, "caption"))
        if view.warning:
            box.append(_label(view.warning, "warning"))
        if view.progress_text is not None:
            running = Gtk.Box(spacing=8)
            running.append(Gtk.Spinner(spinning=True))
            running.append(_label(RUNNING_TITLE, "title-4"))
            box.append(running)
            box.append(_label(view.progress_text, "caption", "dim-label"))
        if view.verdict is not None:
            box.append(_label(view.verdict, "title-4"))
        for note in view.verdict_notes:
            box.append(_label(note, "caption"))
        if view.state_rows:
            rows = _list()
            for title, chip in view.state_rows:
                row = Adw.ActionRow(title=title)
                row.set_use_markup(False)
                row.add_suffix(_chip(chip))
                rows.append(row)
            box.append(rows)
        if view.causes_running:
            causes = Gtk.Box(spacing=8)
            causes.append(Gtk.Spinner(spinning=True))
            causes.append(_label(CAUSES_RUNNING))
            box.append(causes)
        elif view.causes_text:
            box.append(_label(view.causes_text))
        buttons = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=6,
            row_spacing=6,
            homogeneous=False,
            max_children_per_line=4,
        )
        for action in view.actions:
            button = Gtk.Button(label=action.label)
            if action.primary:
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda _b, code=action.code: self._on_recommendation(code))
            buttons.append(button)
        if view.can_copy:
            copy = Gtk.Button(label=COPY)
            copy.connect("clicked", self.on_copy)
            buttons.append(copy)
        if view.can_export:
            export = Gtk.Button(label=EXPORT)
            export.connect("clicked", self.on_export)
            buttons.append(export)
        if buttons.get_first_child() is not None:
            box.append(buttons)
        return box

    def _card(self, card: Card) -> Gtk.Widget:
        suffix = Gtk.Box(spacing=8)
        if card.previous:
            suffix.append(_chip(Chip(PREVIOUS)))
        if card.chip is not None:
            suffix.append(_chip(card.chip))
        if card.section is not None:
            retry = Gtk.Button(label=RETRY, sensitive=card.retry_enabled)
            retry.add_css_class("flat")
            retry.connect("clicked", lambda _b, section=card.section: self._on_retry(section))
            suffix.append(retry)
        box = _section(card.title, suffix)
        for line in card.lines:
            box.append(_label(line))
        if card.progress is not None:
            box.append(Gtk.ProgressBar(fraction=card.progress))
        if card.groups:
            rows = _list()
            for item in card.groups:
                self._add_group(rows, card, item)
            box.append(rows)
        for note in card.notes:
            box.append(_label(note, "caption", "dim-label"))
        return box

    def _add_group(self, parent: Gtk.ListBox, card: Card, item: Group) -> None:
        if item.expanded:
            for row in item.rows:
                parent.append(_row(row))
            return
        key = (card.title, item.title)
        expander = Adw.ExpanderRow(title=item.title, subtitle=item.summary)
        expander.set_use_markup(False)
        expander.set_subtitle_lines(0)
        filled = {"done": False}

        def fill() -> None:
            # Строки создаются при раскрытии: технических наблюдений бывают сотни.
            if not filled["done"]:
                filled["done"] = True
                for row in item.rows:
                    expander.add_row(_row(row))

        def on_expanded(widget, _pspec) -> None:
            if widget.get_expanded():
                self._expanded.add(key)
                fill()
            else:
                self._expanded.discard(key)

        expander.connect("notify::expanded", on_expanded)
        if key in self._expanded:
            expander.set_expanded(True)
            fill()
        parent.append(expander)

    def _methodology(self, view: DiagnosticsView) -> Gtk.Widget:
        rows = _list()
        card = Card("Методика")
        item = Group(
            "Что и как проверяется", "Методика, ограничения и приватность", view.methodology
        )
        self._add_group(rows, card, item)
        return rows
