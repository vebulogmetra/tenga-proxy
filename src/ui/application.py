"""GTK4 + libadwaita application shell."""

from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from src.core import platform_info
from src.core.context import AppContext, get_context
from src.core.core_update import fetch_releases
from src.core.main_loop import GLibLoop
from src.ui.controller import CONFIRM_URL_CHANGE, AppController, resume_monitoring
from src.ui.logic.profiles_view import SortKey
from src.ui.logic.version import app_version, core_version
from src.ui.window import APP_ICON, MainWindow, apply_theme, load_css, load_icons

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("tenga.ui.application")

APP_ID = "ru.tenga.Proxy"
FAILOVER_NOTIFICATION_ID = "failover"


def _network_available() -> bool:
    """Whether the machine has a network at all, as the desktop sees it."""
    return Gio.NetworkMonitor.get_default().get_network_available()


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
    "app.test-latency": ["<Control>t"],
    "app.search": ["<Control>f"],
}


class _GtkShell:
    """`Shell` контроллера поверх `TengaApplication`: окно, трей, диалоги, действия.

    Все обращения к окну идут через `app._window` в момент вызова: окно
    создаётся при активации и исчезает в `reset_for_tests`.
    """

    def __init__(self, app: TengaApplication) -> None:
        self._app = app

    def _window(self):
        return self._app._window

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._app.toast(text, button=button, action=action)

    def notify(self, text: str) -> None:
        self._app.last_notification_for_test = text
        notification = Gio.Notification.new("Veblock")
        notification.set_body(text)
        self._app.send_notification(FAILOVER_NOTIFICATION_ID, notification)

    def has_window(self) -> bool:
        return self._window() is not None

    def refresh_status(self) -> None:
        window = self._window()
        if window is not None:
            window.refresh_status()

    def refresh_pages(self) -> None:
        window = self._window()
        if window is not None:
            window.refresh_pages()

    def show_connecting(self, profile_name: str) -> None:
        window = self._window()
        if window is not None:
            window.show_connecting(profile_name)

    def show_error(self, message: str) -> None:
        window = self._window()
        if window is not None:
            window.show_error(message)

    def selected_profile_id(self) -> int | None:
        window = self._window()
        if window is None:
            return None
        return window.profiles_page.get_selected_profile_id()

    def sort_by_ping(self) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.set_sort(SortKey.PING, ascending=True)

    def set_ping_progress(self, progress) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.set_ping_progress(progress)

    def update_group_progress(self, group_id: int) -> None:
        window = self._window()
        if window is not None:
            window.profiles_page.update_group_progress(group_id)

    def set_tray_state(self, state, profile_name: str) -> None:
        if self._app.tray is not None:
            self._app.tray.set_state(state, profile_name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        action = self._app.lookup_action(name)
        if action is not None:
            action.set_enabled(enabled)

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None) -> None:
        from src.ui.dialogs.confirm import (
            build_delete_confirmation,
            build_url_change_confirmation,
        )

        if kind == CONFIRM_URL_CHANGE:
            dialog = build_url_change_confirmation(heading, body, on_confirm)
        else:
            dialog = build_delete_confirmation(
                heading, body, on_confirm, confirm_label=confirm_label or "Удалить"
            )
        self._app.present_dialog(dialog)

    def open_subscription_form(self, name: str, url: str) -> None:
        from src.ui.dialogs.subscription import SubscriptionDialog

        dialog = SubscriptionDialog()
        dialog.name_row.set_text(name)
        dialog.url_row.set_text(url)
        dialog.connect("subscription-ready", lambda _d, n, u: self._app.add_subscription(n, u))
        self._app.present_dialog(dialog)

    def open_routing_import(self, rows, on_confirm) -> None:
        from src.ui.dialogs.routing_import import RoutingImportDialog

        self._app.present_dialog(RoutingImportDialog(rows, on_confirm))


class TengaApplication(Adw.Application):
    """Application object owning the window, global actions and signals."""

    __gtype_name__ = "TengaApplication"

    def __init__(
        self,
        context: AppContext | None = None,
        lock=None,
        *,
        with_tray: bool = False,
        lock_path=None,
    ) -> None:
        flags = Gio.ApplicationFlags.HANDLES_OPEN
        if platform_info.IS_WINDOWS:
            # Уникальность GApplication держится на D-Bus, которой на Windows нет;
            # её обеспечивают mutex и pipe активации (src/sys/windows).
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.context = context or get_context()
        self._lock = lock
        self._lock_path = lock_path
        self._activation = None
        self.tray = None
        self._with_tray = with_tray
        self._signal_source_ids: list[int] = []
        self._window: MainWindow | None = None
        self._dialog = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        self.controller = self._make_controller()

    def _make_controller(self) -> AppController:
        return AppController(
            self.context,
            _GtkShell(self),
            GLibLoop(),
            network_available=_network_available,
            # Лямбда, а не ссылка: тесты подменяют `app_version` в этом модуле.
            app_version=lambda: app_version(),
        )

    # Жизненный цикл

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_icons()
        load_css()
        apply_theme(getattr(self.context.config, "theme", None))
        self._register_actions()
        self._setup_signal_handlers()
        self._start_activation_server()
        self.watch_monitor()
        if self._with_tray:
            self.start_tray()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(application=self, context=self.context)
        self._window.present()
        self.resume_monitoring()
        self.controller.refresh_core_releases_if_due()
        self.controller.refresh_app_releases_if_due()

    def do_open(self, files, _n_files, _hint) -> None:
        self.activate()
        for source in files:
            self.import_app_link(source.get_uri())

    def do_shutdown(self) -> None:
        # Выход по SIGTERM не эмитирует close-request, поэтому геометрия
        # сохраняется здесь: этот путь общий для всех способов завершения.
        if self._window is not None:
            self._window.save_geometry()

        # Ядро гасится до снятия блокировки: иначе следующий экземпляр
        # запустится, пока этот ещё держит TUN-интерфейс.
        self.controller.shutdown()

        self.stop_tray()

        for source_id in self._signal_source_ids:
            GLib.source_remove(source_id)
        self._signal_source_ids.clear()
        self._stop_activation_server()

        if self._lock is not None:
            self._lock.release()

        Adw.Application.do_shutdown(self)

    # Действия

    def _register_actions(self) -> None:
        # Лямбды, а не связанные методы: `reset_for_tests` создаёт новый
        # контроллер, и действия должны разыменовывать `self.controller`
        # в момент вызова, иначе кликали бы в контроллер прежнего контекста.
        handlers: dict[str, Callable[[], None]] = {
            "connect": lambda: self.controller.connect_selected(),
            "disconnect": lambda: self.controller.disconnect_proxy(),
            "toggle-connection": lambda: self.controller.toggle_connection(),
            "add-profile": self._open_add_profile,
            "add-profile-from-clipboard": self._add_profile_from_clipboard,
            "add-subscription": self._open_add_subscription,
            "add-group": self._open_add_group,
            "refresh-subscriptions": lambda: self.controller.refresh_subscriptions(),
            "test-latency": lambda: self.controller.test_latency(),
            "search": self._toggle_search,
            "settings": self._open_settings,
            "about": self._open_about,
            "shortcuts": self._open_shortcuts,
            "quit": self.quit,
            "hide-window": self._hide_window,
            "activate-window": self._activate_window,
            "restore-routing": lambda: self.controller.restore_routing(),
        }

        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=handler: fn())
            self.add_action(action)
        self.controller.sync_restore_routing()

        # Действие с параметром: трей адресует конкретный профиль числом, как
        # это делают строчные действия окна.
        connect_profile = Gio.SimpleAction.new("connect-profile", GLib.VariantType.new("i"))
        connect_profile.connect(
            "activate", lambda _action, param: self.controller.connect_profile(param.get_int32())
        )
        self.add_action(connect_profile)

        for detailed_name, accels in _ACCELS.items():
            self.set_accels_for_action(detailed_name, accels)

    # Трей

    def start_tray(self, item=None) -> None:
        """Publish the tray icon."""
        from src.ui.tray.controller import TrayController

        if self.tray is not None:
            return
        try:
            self.tray = TrayController(self, self.context, item=item)
            self.tray.start()
        except Exception as e:
            # Без панели, поддерживающей StatusNotifierItem, приложение просто
            # работает без иконки: это не повод не запускаться.
            logger.info("Tray is unavailable: %s", e)
            self.tray = None

    def stop_tray(self) -> None:
        """Remove the tray icon."""
        if self.tray is None:
            return
        self.tray.stop()
        self.tray = None

    # Делегаты контроллера: их зовут окно, трей, run_app и тесты

    def set_app_release_fetcher(self, fetcher) -> None:
        self.controller.set_app_release_fetcher(fetcher)

    def set_release_fetcher(self, fetch) -> None:
        self.controller.set_release_fetcher(fetch)

    def import_app_link(self, raw: str) -> None:
        self.controller.import_app_link(raw)

    def resume_monitoring(self) -> None:
        # Функция модуля, а не метод контроллера: тест монитора зовёт этот
        # метод на SimpleNamespace, у которого есть только `context`.
        resume_monitoring(self.context)

    def watch_monitor(self) -> None:
        self.controller.watch_monitor()

    def notify_user(self, text: str) -> None:
        self.controller.notify_user(text)

    def set_connection_service(self, service) -> None:
        self.controller.set_connection_service(service)

    def connect_profile(self, profile_id: int) -> None:
        self.controller.connect_profile(profile_id)

    def disconnect_proxy(self) -> None:
        self.controller.disconnect_proxy()

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        return self.controller.add_profile_from_bean(bean, group_id=group_id)

    def delete_profile(self, profile_id: int) -> None:
        self.controller.delete_profile(profile_id)

    def add_subscription(self, name: str, url: str):
        return self.controller.add_subscription(name, url)

    def add_group(self, name: str):
        return self.controller.add_group(name)

    def update_group(self, group_id: int, *, name: str, url: str | None = None):
        return self.controller.update_group(group_id, name=name, url=url)

    def delete_group(self, group_id: int) -> None:
        self.controller.delete_group(group_id)

    def save_profiles(self) -> None:
        self.controller.save_profiles()

    def apply_settings(self) -> bool:
        return self.controller.apply_settings()

    def restore_routing(self) -> None:
        self.controller.restore_routing()

    def reconnect_current(self) -> None:
        self.controller.reconnect_current()

    def set_latency_probe(self, probe) -> None:
        self.controller.set_latency_probe(probe)

    def set_subscription_updater(self, updater) -> None:
        self.controller.set_subscription_updater(updater)

    def set_profile_activation_handler(self, handler) -> None:
        self.controller.set_profile_activation_handler(handler)

    def select_profile(self, profile_id: int) -> None:
        self.controller.select_profile(profile_id)

    def update_subscription(self, group_id: int) -> None:
        self.controller.update_subscription(group_id)

    def keep_working_profiles(self, group_id: int) -> None:
        self.controller.keep_working_profiles(group_id)

    def test_latency_for(self, profile_id: int) -> None:
        self.controller.test_latency_for(profile_id)

    def test_latency_for_group(self, group_id: int) -> None:
        self.controller.test_latency_for_group(group_id)

    # Имена с подчёркиванием читают существующие тесты.

    def _default_subscription_updater(self, group_id: int, url: str) -> int:
        return self.controller.default_subscription_updater(group_id, url)

    @property
    def _app_update_thread(self):
        return self.controller.app_update_thread

    # Диалоги

    def present_dialog(self, dialog) -> bool:
        """Show a dialog unless another one is already open.

        Диалоги не складываются стопкой: повторное нажатие Ctrl+N или клик
        по пункту меню при открытой форме ничего не делает. Слот освобождает
        сигнал `closed`, а не вызывающий: диалог закрывается и кнопкой, и
        Esc, и щелчком мимо, и отследить это иначе нельзя.
        """
        if self._dialog is not None:
            return False
        self._dialog = dialog
        dialog.connect("closed", self._on_dialog_closed)
        dialog.present(self._window)
        return True

    def _on_dialog_closed(self, dialog) -> None:
        if self._dialog is dialog:
            self._dialog = None

    @property
    def current_dialog(self):
        """The dialog on screen, if any."""
        return self._dialog

    def _open_add_profile(self, link: str = "") -> None:
        from src.ui.dialogs.add_profile import AddProfileDialog

        dialog = AddProfileDialog()
        if link:
            dialog.link_row.set_text(link)
        dialog.connect("profile-ready", lambda _d, bean: self.add_profile_from_bean(bean))
        self.present_dialog(dialog)

    def _add_profile_from_clipboard(self) -> None:
        """Open the add dialog with the clipboard already pasted in."""
        from src.ui.dialogs.base import read_clipboard

        read_clipboard(self._open_add_profile)

    def _open_add_subscription(self) -> None:
        from src.ui.dialogs.subscription import SubscriptionDialog

        dialog = SubscriptionDialog()
        dialog.connect("subscription-ready", lambda _d, name, url: self.add_subscription(name, url))
        self.present_dialog(dialog)

    def _open_add_group(self) -> None:
        from src.ui.dialogs.group import GroupDialog

        dialog = GroupDialog()
        dialog.connect("group-ready", lambda _d, name: self.add_group(name))
        self.present_dialog(dialog)

    def _open_settings(self) -> None:
        from src.ui.dialogs.settings import SettingsDialog

        dialog = SettingsDialog(self.context.config, context=self.context)
        # `Adw.PreferencesDialog` не имеет кнопки подтверждения: по конвенции
        # GNOME настройки применяются при закрытии.
        dialog.connect("settings-saved", lambda _d: self.apply_settings())
        self.present_dialog(dialog)

    def _open_about(self) -> None:
        core = core_version(getattr(self.context, "xray_manager", None))
        dialog = Adw.AboutDialog(
            application_name="Veblock",
            application_icon=APP_ICON,
            developer_name="Artem G.",
            version=app_version(),
            comments=f"Клиент прокси для Linux на базе xray-core {core}",
            website="https://github.com/vebulogmetra/tenga-proxy",
            license_type=Gtk.License.MIT_X11,
        )
        # Строку целиком копируют в отчёт об ошибке, поэтому обе версии рядом.
        dialog.set_debug_info(f"Veblock {app_version()}\nxray-core {core}")
        self.present_dialog(dialog)

    def _open_shortcuts(self) -> None:
        from src.ui.shortcuts import ShortcutsDialog

        self.present_dialog(ShortcutsDialog())

    # Действия страниц

    def _toggle_search(self) -> None:
        if self._window is not None:
            self._window.search_button.set_active(not self._window.search_button.get_active())

    # Ожидание фоновых задач: только для тестов, в рабочем коде всё идёт
    # через главный цикл.

    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.core_update_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    def wait_for_connection_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.connection_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    def wait_for_latency_for_test(self, timeout: float = 10.0) -> None:
        runner = self.controller.latency_runner
        if runner is not None:
            runner.wait(timeout)
        self._drain_main_context()

    def wait_for_subscriptions_for_test(self, timeout: float = 10.0) -> None:
        thread = self.controller.subscriptions_thread
        if thread is not None:
            thread.join(timeout)
        self._drain_main_context()

    @staticmethod
    def _drain_main_context() -> None:
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def _hide_window(self) -> None:
        if self._window is not None:
            self._window.set_visible(False)

    def _activate_window(self) -> None:
        """Show the window, creating it if the application ran headless."""
        self.activate()
        if self._window is not None:
            self._window.set_visible(True)
            self._window.present()

    def activate_action(self, name: str, target=None) -> None:
        """Run one of the application actions, wrapping an integer target.

        `Gio.Action` требует `GLib.Variant`, а трей адресует профиль обычным
        числом: приведение живёт здесь, чтобы вызывающие о нём не знали.
        Вызов синхронный, в отличие от унаследованного `Gio.Application`:
        тому нужен прогон главного цикла, и результат виден не сразу.
        """
        action = self.lookup_action(name)
        if action is None:
            logger.warning("Unknown action %s", name)
            return

        if isinstance(target, GLib.Variant) or target is None:
            parameter = target
        else:
            parameter = GLib.Variant("i", int(target))
        action.activate(parameter)

    def reset_for_tests(self, context: AppContext | None) -> None:
        """Rebind the application to another context and drop the window.

        Существует ради тестов: создать второе приложение нельзя, GApplication
        занимает путь на шине сессии до конца процесса.
        """
        self.stop_tray()
        if self._window is not None:
            self._window.detach()
            self._window.destroy()
            self._window = None
        if context is not None:
            self.context = context
        self.controller = self._make_controller()
        self._dialog = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        # Действие пережило бы смену контекста с состоянием прежнего.
        self.controller.sync_restore_routing()

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        """Show a message in the window, if there is one."""
        # Последнее сообщение хранится и без окна: тосты — единственный
        # видимый результат многих действий, и тестам нужно их читать.
        self.last_toast_for_test = text
        if self._window is not None:
            self._window.toast(text, button=button, action=action)

    # Сигналы

    def _setup_signal_handlers(self) -> None:
        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK).

        На Windows `GLib.unix_signal_add` нет, а закрытие приходит оконными
        сообщениями, которые GTK обрабатывает сам.
        """
        if platform_info.IS_WINDOWS:
            self._signal_source_ids = []
            return
        self._signal_source_ids = [
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal, signum)
            for signum in (signal.SIGINT, signal.SIGTERM)
        ]

    # Активация второго запуска на Windows

    def _start_activation_server(self) -> None:
        if not platform_info.IS_WINDOWS or self._lock is None or self._lock_path is None:
            return
        from src.sys.windows.activation import ActivationServer, pipe_address

        def deliver(uris: list[str]) -> None:
            def _apply() -> bool:
                self.activate()
                for uri in uris:
                    self.import_app_link(uri)
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply)

        try:
            self._activation = ActivationServer(pipe_address(str(self._lock_path)), deliver)
            self._activation.start()
        except OSError as e:
            logger.warning("Activation server did not start: %s", e)
            self._activation = None

    def _stop_activation_server(self) -> None:
        if self._activation is not None:
            self._activation.stop()
            self._activation = None

    def _on_signal(self, signum: int) -> bool:
        logger.info("Received signal %s, terminating application", signum)
        self.quit()
        return GLib.SOURCE_REMOVE


def run_app(config_dir=None, lock=None, with_tray: bool = True, uris=(), lock_path=None) -> int:
    """Entry point for the GTK4 interface."""
    from src.core.context import init_context
    from src.core.monitor import attach_monitor

    context = init_context(config_dir=config_dir)
    # Монитор заводится здесь: без него страница мониторинга пуста, а
    # подключение не начинает наблюдение — `ConnectionService` запускает уже
    # готовый монитор, но сам его не создаёт.
    attach_monitor(context)
    app = TengaApplication(context=context, lock=lock, with_tray=with_tray, lock_path=lock_path)
    app.set_release_fetcher(fetch_releases)
    from src.core.app_update import fetch_app_releases
    from src.sub.route import local_proxy_url

    app.set_app_release_fetcher(
        lambda: fetch_app_releases(lambda: local_proxy_url(context.config, context.proxy_state))
    )
    return app.run(["tenga-proxy", *uris])
