"""Diagnostics page: connection state, routing summary, manual checks and the log."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, GObject, Gtk, Pango

from src.ui.logic.monitoring_view import (
    CLASS_DIM,
    CLASS_ERROR,
    CLASS_OK,
    LAST_CHECK_PENDING,
    MonitoringRow,
    MonitoringView,
)

_STATE_CLASSES = (CLASS_OK, CLASS_ERROR, CLASS_DIM)

SECTION_CONNECTION = "connection"
SECTION_ROUTING = "routing"


class MonitoringPage(Gtk.Box):
    """Diagnostics on the right of the window: state, routing, checks and the log."""

    __gtype_name__ = "TengaMonitoringPage"

    __gsignals__ = {
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "diagnostics-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("card")
        self.add_css_class("diagnostics-card")

        # Строки создаются один раз и обновляются на месте: пересборка групп на
        # каждом тике мониторинга (по умолчанию раз в 10 секунд) сбрасывала бы
        # прокрутку и фокус.
        #
        # Ключ включает секцию: заголовок «VPN» встречается и в состоянии
        # соединения, и в правилах маршрутизации, и по одному имени эти строки
        # затирали бы друг друга.
        self._rows: dict[tuple[str, str], Adw.ActionRow] = {}
        self._values: dict[tuple[str, str], Gtk.Label] = {}
        self._groups: list[Adw.PreferencesGroup] = []

        top = Gtk.Box(spacing=16, homogeneous=True)
        self._connection_group = self._group("Состояние соединения")
        self._routing_group = self._group("Маршрутизация")
        top.append(self._connection_group)
        top.append(self._routing_group)
        self.append(top)

        self._build_checks()

        self._diagnostics_busy = False
        self._diagnostics_timer = 0
        log_group = self._group(
            "Журнал", description="Последние записи. Хранение — 3 дня; секреты маскируются."
        )
        log_group.set_vexpand(True)
        self.log_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE)
        self.log_view.add_css_class("diagnostics-log")
        scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
        scroll.add_css_class("card")
        scroll.set_child(self.log_view)
        log_group.add(scroll)

        controls = Gtk.Box(spacing=8, margin_top=8)
        self.wrap_check = Gtk.CheckButton(label="Перенос строк")
        self.wrap_check.connect("toggled", self._on_wrap_toggled)
        controls.append(self.wrap_check)
        controls.append(Gtk.Box(hexpand=True))
        self.log_buttons: list[Gtk.Button] = []
        for label, callback in (
            ("Обновить", self.refresh_diagnostics),
            ("Экспорт…", self._export_diagnostics),
            ("Очистить", self._clear_diagnostics),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            controls.append(button)
            self.log_buttons.append(button)
        log_group.add(controls)
        self.append(log_group)

    def _group(self, title: str, *, description: str | None = None) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title, description=description)
        self._groups.append(group)
        return group

    def _build_checks(self) -> None:
        self._last_check = Gtk.Label(label=LAST_CHECK_PENDING, xalign=0.0)
        self._last_check.add_css_class("dim-label")
        self.append(self._last_check)

        buttons = Gtk.Box(spacing=8, homogeneous=True)
        self.check_button = Gtk.Button(label="Проверить сейчас")
        self.check_button.connect("clicked", lambda _b: self.emit("refresh-requested"))
        buttons.append(self.check_button)
        self.diagnostics_button = Gtk.Button(label="Диагностика сети…")
        self.diagnostics_button.connect("clicked", lambda _b: self.emit("diagnostics-requested"))
        buttons.append(self.diagnostics_button)
        self.append(buttons)

    def _on_wrap_toggled(self, button: Gtk.CheckButton) -> None:
        self.log_view.set_wrap_mode(
            Gtk.WrapMode.WORD_CHAR if button.get_active() else Gtk.WrapMode.NONE
        )

    def set_active(self, active: bool) -> None:
        """Run the log timer only while the page is on screen.

        Окно зовёт это при переключении страниц и при скрытии: map/unmap у
        страницы в стеке не различает свёрнутое окно и спрятанную страницу.
        """
        if active:
            self._start_diagnostics()
        else:
            self._stop_diagnostics()

    def focus_log(self) -> None:
        self.log_view.grab_focus()

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
        self._last_check.set_text(view.last_check_line or view.last_check)

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

    def get_group_titles(self) -> list[str]:
        return [group.get_title() for group in self._groups]

    def log_timer_running_for_test(self) -> bool:
        return bool(self._diagnostics_timer)
