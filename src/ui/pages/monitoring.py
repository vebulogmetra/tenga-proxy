"""Monitoring page: connection state, routing summary and a manual refresh."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, GObject, Gtk, Pango

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
        self._diagnostics_busy = False
        self._diagnostics_timer = 0
        group = Adw.PreferencesGroup(
            title="Журнал", description="Последние записи. Хранение — 3 дня; секреты маскируются."
        )
        self.add(group)
        self.log_view = Gtk.TextView(
            editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR
        )
        scroll = Gtk.ScrolledWindow(min_content_height=160, max_content_height=260)
        scroll.set_child(self.log_view)
        group.add(scroll)
        buttons = Gtk.Box(spacing=8)
        for label, callback in (
            ("Обновить журнал", self.refresh_diagnostics),
            ("Экспортировать", self._export_diagnostics),
            ("Очистить", self._clear_diagnostics),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            buttons.append(button)
        group.add(buttons)
        self.connect("map", self._start_diagnostics)
        self.connect("unmap", self._stop_diagnostics)

    def _log_dir(self):
        from src.core.config import LOG_DIR

        return LOG_DIR

    def _start_diagnostics(self, *_args):
        self.refresh_diagnostics()
        if not self._diagnostics_timer:
            self._diagnostics_timer = GLib.timeout_add_seconds(2, self._tick_diagnostics)

    def _stop_diagnostics(self, *_args):
        if self._diagnostics_timer:
            GLib.source_remove(self._diagnostics_timer)
            self._diagnostics_timer = 0

    def _tick_diagnostics(self):
        self.refresh_diagnostics()
        return GLib.SOURCE_CONTINUE

    def refresh_diagnostics(self, *_args):
        from src.core.diagnostics_export import read_diagnostics
        from src.ui.logic.async_utils import run_in_background

        if self._diagnostics_busy:
            return
        self._diagnostics_busy = True

        def done(text):
            self._diagnostics_busy = False
            self.log_view.get_buffer().set_text(text)

        def failed(_error):
            self._diagnostics_busy = False

        run_in_background(lambda: read_diagnostics(self._log_dir()), on_done=done, on_error=failed)

    def _export_diagnostics(self, *_args):
        from src.core.diagnostics_export import read_diagnostics
        from src.ui.logic.async_utils import run_in_background

        chooser = Gtk.FileChooserNative(
            title="Экспорт очищенного журнала",
            transient_for=self.get_root(),
            action=Gtk.FileChooserAction.SAVE,
            accept_label="Сохранить",
            cancel_label="Отмена",
        )
        chooser.set_current_name("veblock-diagnostics.txt")

        def response(dialog, response_id):
            selected = dialog.get_file()
            if response_id == Gtk.ResponseType.ACCEPT and selected and selected.get_path():
                from pathlib import Path

                target = Path(selected.get_path())

                def write():
                    target.write_text(read_diagnostics(self._log_dir()), encoding="utf-8")

                def failed(_error):
                    self.log_view.get_buffer().set_text("Не удалось экспортировать журнал")

                run_in_background(write, on_error=failed)
            dialog.destroy()

        chooser.connect("response", response)
        chooser.show()

    def _clear_diagnostics(self, *_args):
        from src.core.log_manager import LogManager
        from src.ui.dialogs.confirm import build_delete_confirmation
        from src.ui.logic.async_utils import run_in_background

        def clear():
            run_in_background(
                lambda: LogManager(self._log_dir()).clear_all_logs(),
                on_done=lambda _result: self.refresh_diagnostics(),
            )

        dialog = build_delete_confirmation(
            "Очистить журналы?",
            "Все сохранённые записи будут удалены.",
            clear,
            confirm_label="Очистить",
        )
        dialog.present(self.get_root())

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
        # Без переноса: строки короткие, а wrap рвал «Не запущен» надвое даже
        # там, где места хватало. Длинную ошибку обрезаем многоточием.
        value.set_ellipsize(Pango.EllipsizeMode.END)
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
