"""Monitoring page: connection state, routing summary and a manual refresh."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.ui.logic.monitoring_view import (
    CLASS_DIM,
    CLASS_ERROR,
    CLASS_OK,
    UNKNOWN,
    MonitoringRow,
    MonitoringView,
)

_STATE_CLASSES = (CLASS_OK, CLASS_ERROR, CLASS_DIM)

SECTION_CONNECTION = "connection"
SECTION_ROUTING = "routing"


class MonitoringPage(Adw.PreferencesPage):
    """Two groups of labelled values plus the refresh control."""

    __gtype_name__ = "TengaMonitoringPage"

    __gsignals__ = {
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__()

        # Строки создаются один раз и обновляются на месте: пересборка групп на
        # каждом тике мониторинга (по умолчанию раз в 10 секунд) сбрасывала бы
        # прокрутку и фокус.
        #
        # Ключ включает секцию: заголовок «VPN» встречается и в состоянии
        # соединения, и в правилах маршрутизации, и по одному имени эти строки
        # затирали бы друг друга.
        self._rows: dict[tuple[str, str], Adw.ActionRow] = {}
        self._values: dict[tuple[str, str], Gtk.Label] = {}

        self._connection_group = Adw.PreferencesGroup(title="Соединение")
        self.add(self._connection_group)

        self._routing_group = Adw.PreferencesGroup(title="Маршрутизация")
        self.add(self._routing_group)

        self._build_footer()

    def _build_footer(self) -> None:
        group = Adw.PreferencesGroup()
        self.add(group)

        row = Adw.ActionRow(title="Последняя проверка")
        self._last_check = Gtk.Label(label=UNKNOWN)
        self._last_check.add_css_class("dim-label")
        row.add_suffix(self._last_check)
        group.add(row)

        self.refresh_button = Gtk.Button(label="Обновить сейчас")
        self.refresh_button.set_halign(Gtk.Align.CENTER)
        self.refresh_button.set_margin_top(12)
        self.refresh_button.connect("clicked", lambda _b: self.emit("refresh-requested"))
        group.add(self.refresh_button)

    def _ensure_row(
        self, section: str, group: Adw.PreferencesGroup, row: MonitoringRow
    ) -> Adw.ActionRow:
        key = (section, row.title)
        existing = self._rows.get(key)
        if existing is not None:
            return existing

        action_row = Adw.ActionRow(title=row.title)
        value = Gtk.Label(label=row.value)
        value.set_wrap(True)
        value.set_xalign(1.0)
        action_row.add_suffix(value)
        group.add(action_row)

        self._rows[key] = action_row
        self._values[key] = value
        return action_row

    def _apply(
        self, section: str, group: Adw.PreferencesGroup, rows: tuple[MonitoringRow, ...]
    ) -> None:
        for row in rows:
            self._ensure_row(section, group, row)
            label = self._values[(section, row.title)]
            label.set_text(row.value)
            for css_class in _STATE_CLASSES:
                label.remove_css_class(css_class)
            if row.css_class:
                label.add_css_class(row.css_class)

    def update(self, view: MonitoringView) -> None:
        """Render the given summary, reusing the existing rows."""
        self._apply(SECTION_CONNECTION, self._connection_group, view.connection)
        self._apply(SECTION_ROUTING, self._routing_group, view.routing)
        self._last_check.set_text(view.last_check)

    # --- аксессоры для тестов ---

    def get_row_count(self) -> int:
        return len(self._rows)

    def get_value(self, title: str, *, section: str = SECTION_CONNECTION) -> str:
        return self._values[(section, title)].get_text()

    def get_classes(self, title: str, *, section: str = SECTION_CONNECTION) -> list[str]:
        classes = self._values[(section, title)].get_css_classes()
        return [c for c in classes if c in _STATE_CLASSES]

    def get_row_widget(self, title: str, *, section: str = SECTION_CONNECTION) -> Adw.ActionRow:
        return self._rows[(section, title)]

    def get_last_check_text(self) -> str:
        return self._last_check.get_text()
