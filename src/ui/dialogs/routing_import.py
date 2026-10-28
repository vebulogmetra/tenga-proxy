"""Подтверждение импорта общей маршрутизации (GTK4)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from src.ui.logic.routing_import import REST_LABEL, ImportRow

CANCEL = "cancel"
IMPORT = "import"


class RoutingImportDialog(Adw.AlertDialog):
    """Строки «подпись — значение»; применяет только ответ «Импортировать»."""

    __gtype_name__ = "TengaRoutingImportDialog"

    def __init__(self, rows: list[ImportRow], on_confirm: Callable[[], None]) -> None:
        super().__init__(
            heading="Импорт маршрутизации",
            body="Текущие списки будут заменены. Вернуть их можно в настройках: "
            "«О приложении» → «Обслуживание».",
        )
        self._titles: list[str] = []
        self.rest_row: Adw.PreferencesRow | None = None
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        for row in rows:
            box.append(self._build_row(row))
        self.set_extra_child(box)

        self.add_response(CANCEL, "Отмена")
        self.add_response(IMPORT, "Импортировать")
        # Не DESTRUCTIVE: импорт обратим откатом. По умолчанию — всё равно «Отмена».
        self.set_response_appearance(IMPORT, Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response(CANCEL)
        self.set_close_response(CANCEL)
        self.connect("response", lambda _d, response: on_confirm() if response == IMPORT else None)

    def _build_row(self, row: ImportRow) -> Adw.PreferencesRow:
        # Значения приходят из ссылки: только текст, без разметки.
        if row.details:
            widget = Adw.ExpanderRow(title=row.label, subtitle=row.value)
            widget.set_use_markup(False)
            for line in row.details:
                child = Adw.ActionRow(title=line)
                child.set_use_markup(False)
                widget.add_row(child)
        else:
            widget = Adw.ActionRow(title=row.label, subtitle=row.value)
            widget.set_use_markup(False)
            widget.set_subtitle_lines(0)
        if row.warning:
            widget.add_css_class("error")
        if row.label == REST_LABEL:
            self.rest_row = widget
        self._titles.append(row.label)
        return widget

    def row_titles(self) -> list[str]:
        return list(self._titles)
