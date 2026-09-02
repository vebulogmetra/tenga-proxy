"""GTK4 + libadwaita application shell."""

from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib

from src.core.context import AppContext, get_context
from src.ui.window import MainWindow, load_css

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("tenga.ui.application")

APP_ID = "ru.tenga.Proxy"

# Действия и их ускорители. Один набор обслуживает меню, контекстные меню,
# клавиатуру и трей — как описано в дизайн-документе.
_ACCELS: dict[str, list[str]] = {
    "app.add-profile": ["<Control>n"],
    "app.add-subscription": ["<Control><Shift>n"],
    "app.settings": ["<Control>comma"],
    "app.refresh-subscriptions": ["F5"],
    "app.quit": ["<Control>q"],
    "app.hide-window": ["<Control>w"],
    "app.toggle-connection": ["<Control>Return"],
}


class TengaApplication(Adw.Application):
    """Application object owning the window, global actions and signals."""

    __gtype_name__ = "TengaApplication"

    def __init__(self, context: AppContext | None = None, lock=None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.context = context or get_context()
        self._lock = lock
        self._signal_source_ids: list[int] = []
        self._window: MainWindow | None = None

    # Жизненный цикл

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_css()
        self._register_actions()
        self._setup_signal_handlers()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(application=self, context=self.context)
        self._window.present()

    def do_shutdown(self) -> None:
        # Выход по SIGTERM не эмитирует close-request, поэтому геометрия
        # сохраняется здесь: этот путь общий для всех способов завершения.
        if self._window is not None:
            self._window.save_geometry()

        for source_id in self._signal_source_ids:
            GLib.source_remove(source_id)
        self._signal_source_ids.clear()

        if self._lock is not None:
            self._lock.release()

        Adw.Application.do_shutdown(self)

    # Действия

    def _register_actions(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "connect": self._not_implemented("connect"),
            "disconnect": self._not_implemented("disconnect"),
            "toggle-connection": self._not_implemented("toggle-connection"),
            "add-profile": self._not_implemented("add-profile"),
            "add-profile-from-clipboard": self._not_implemented("add-profile-from-clipboard"),
            "add-subscription": self._not_implemented("add-subscription"),
            "add-group": self._not_implemented("add-group"),
            "refresh-subscriptions": self._not_implemented("refresh-subscriptions"),
            "settings": self._not_implemented("settings"),
            "about": self._not_implemented("about"),
            "shortcuts": self._not_implemented("shortcuts"),
            "quit": self.quit,
            "hide-window": self._hide_window,
        }

        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=handler: fn())
            self.add_action(action)

        for detailed_name, accels in _ACCELS.items():
            self.set_accels_for_action(detailed_name, accels)

    def _not_implemented(self, name: str) -> Callable[[], None]:
        """Placeholder handler until pages and dialogs arrive in phase 2."""

        def handler() -> None:
            logger.info("Action %s is not implemented yet", name)
            self.toast(f"«{name}» появится на следующем этапе")

        return handler

    def _hide_window(self) -> None:
        if self._window is not None:
            self._window.set_visible(False)

    def reset_for_tests(self, context: AppContext | None) -> None:
        """Rebind the application to another context and drop the window.

        Существует ради тестов: создать второе приложение нельзя, GApplication
        занимает путь на шине сессии до конца процесса.
        """
        if self._window is not None:
            self._window.destroy()
            self._window = None
        if context is not None:
            self.context = context

    def toast(self, text: str) -> None:
        """Show a message in the window, if there is one."""
        if self._window is not None:
            self._window.toast(text)

    # Сигналы

    def _setup_signal_handlers(self) -> None:
        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK)."""
        self._signal_source_ids = [
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal, signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        ]

    def _on_signal(self, signum: int) -> bool:
        logger.info("Received signal %s, terminating application", signum)
        self.quit()
        return GLib.SOURCE_REMOVE


def run_app(config_dir=None, lock=None) -> int:
    """Entry point for the GTK4 interface."""
    from src.core.context import init_context

    context = init_context(config_dir=config_dir)
    app = TengaApplication(context=context, lock=lock)
    return app.run([])
