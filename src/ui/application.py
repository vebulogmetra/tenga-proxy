"""GTK4 + libadwaita application shell."""

from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from src.core.context import AppContext, get_context
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner
from src.ui.logic.status import ConnectionState
from src.ui.logic.version import app_version
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
    "app.test-latency": ["<Control>t"],
    "app.search": ["<Control>f"],
}


class TengaApplication(Adw.Application):
    """Application object owning the window, global actions and signals."""

    __gtype_name__ = "TengaApplication"

    def __init__(
        self, context: AppContext | None = None, lock=None, *, with_tray: bool = False
    ) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.context = context or get_context()
        self._lock = lock
        self.tray = None
        self._with_tray = with_tray
        self._signal_source_ids: list[int] = []
        self._window: MainWindow | None = None
        self._latency_runner: LatencyRunner | None = None
        self._latency_probe: Callable[[int], int] | None = None
        self._subscription_updater: Callable[[int, str], int] | None = None
        self._subscriptions_thread = None
        self._profile_activation_handler: Callable[[int], None] | None = None
        self._connection_service = None
        self._connection_thread = None
        self._dialog = None
        self.last_toast_for_test = ""

    # Жизненный цикл

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_css()
        self._register_actions()
        self._setup_signal_handlers()
        if self._with_tray:
            self.start_tray()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(application=self, context=self.context)
        self._window.present()

    def do_shutdown(self) -> None:
        # Выход по SIGTERM не эмитирует close-request, поэтому геометрия
        # сохраняется здесь: этот путь общий для всех способов завершения.
        if self._window is not None:
            self._window.save_geometry()

        self.stop_tray()

        for source_id in self._signal_source_ids:
            GLib.source_remove(source_id)
        self._signal_source_ids.clear()

        if self._lock is not None:
            self._lock.release()

        Adw.Application.do_shutdown(self)

    # Действия

    def _register_actions(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "connect": self._connect_selected,
            "disconnect": self.disconnect_proxy,
            "toggle-connection": self._toggle_connection,
            "add-profile": self._open_add_profile,
            "add-profile-from-clipboard": self._add_profile_from_clipboard,
            "add-subscription": self._open_add_subscription,
            "add-group": self._open_add_group,
            "refresh-subscriptions": self._refresh_subscriptions,
            "test-latency": self._test_latency,
            "search": self._toggle_search,
            "settings": self._open_settings,
            "about": self._open_about,
            "shortcuts": self._open_shortcuts,
            "quit": self.quit,
            "hide-window": self._hide_window,
            "activate-window": self._activate_window,
        }

        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=handler: fn())
            self.add_action(action)

        # Действие с параметром: трей адресует конкретный профиль числом, как
        # это делают строчные действия окна.
        connect_profile = Gio.SimpleAction.new("connect-profile", GLib.VariantType.new("i"))
        connect_profile.connect(
            "activate", lambda _action, param: self.connect_profile(param.get_int32())
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

    # Подключение

    def set_connection_service(self, service) -> None:
        """Install the object starting and stopping the proxy."""
        self._connection_service = service

    def _ensure_connection_service(self):
        if self._connection_service is None:
            from src.core.connection import ConnectionService

            self._connection_service = ConnectionService(self.context)
        return self._connection_service

    def _connection_busy(self) -> bool:
        return self._connection_thread is not None and self._connection_thread.is_alive()

    def connect_profile(self, profile_id: int) -> None:
        """Start the proxy for one profile in the background."""
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        if self._connection_busy():
            # Два одновременных запуска оставили бы висящий процесс xray.
            self.toast("Подключение уже выполняется")
            return

        if self._window is not None:
            self._window.show_connecting(profile.name)
        if self.tray is not None:
            # Промежуточное состояние живёт только в UI: в proxy_state его нет,
            # и сам по себе трей о нём не узнает.
            self.tray.set_state(ConnectionState.CONNECTING, profile.name)

        service = self._ensure_connection_service()
        self._connection_thread = run_in_background(
            lambda: service.connect(profile_id),
            on_done=lambda result: self._on_connection_done(result, profile.name),
            on_error=self._on_connection_failed,
            name="tenga-connect",
        )

    def disconnect_proxy(self) -> None:
        """Stop the proxy in the background."""
        if self._connection_busy():
            self.toast("Подключение уже выполняется")
            return

        service = self._ensure_connection_service()
        self._connection_thread = run_in_background(
            service.disconnect,
            on_done=lambda result: self._on_disconnection_done(result),
            on_error=self._on_connection_failed,
            name="tenga-disconnect",
        )

    def _connect_selected(self) -> None:
        profile_id = self._selected_profile_id()
        if profile_id is None:
            self.toast("Выберите профиль в списке")
            return
        self.connect_profile(profile_id)

    def _toggle_connection(self) -> None:
        if self.context.proxy_state.is_running:
            self.disconnect_proxy()
            return
        self._connect_selected()

    def _selected_profile_id(self) -> int | None:
        if self._window is None:
            return None
        return self._window.profiles_page.get_selected_profile_id()

    def _on_connection_done(self, result, profile_name: str) -> None:
        if result.ok:
            self.toast(f"Подключено: {profile_name}")
        else:
            self.toast(f"Не удалось подключиться: {result.error}")
            if self._window is not None:
                self._window.show_error(result.error)
            if self.tray is not None:
                self.tray.set_state(ConnectionState.ERROR, "")

        self._refresh_window()

    def _on_disconnection_done(self, result) -> None:
        if result.ok:
            self.toast("Отключено")
        else:
            self.toast(f"Не удалось отключиться: {result.error}")
        self._refresh_window()

    def _on_connection_failed(self, error: BaseException) -> None:
        self.toast(f"Ошибка подключения: {error}")
        if self._window is not None:
            self._window.show_error(str(error))
        if self.tray is not None:
            self.tray.set_state(ConnectionState.ERROR, "")
        self._refresh_window()

    def _refresh_window(self) -> None:
        if self._window is not None:
            self._window.refresh_status()
            self._window.refresh_pages()

    # Изменение данных

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        """Store a parsed profile and persist it."""
        entry = self.context.profiles.add_profile(bean, group_id=group_id)
        self._save_profiles()
        self._refresh_pages()
        self.toast(f"Профиль добавлен: {entry.name}")
        return entry

    def delete_profile(self, profile_id: int) -> None:
        """Remove one profile."""
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        name = profile.name
        self.context.profiles.remove_profile(profile_id)
        self._save_profiles()
        self._refresh_pages()
        self.toast(f"Профиль удалён: {name}")

    def add_subscription(self, name: str, url: str):
        """Create a subscription group and fetch it right away."""
        group = self.context.profiles.add_group(name, is_subscription=True)
        group.subscription_url = url
        self._save_profiles()
        self._refresh_pages()
        self.update_subscription(group.id)
        return group

    def add_group(self, name: str):
        """Create a plain group."""
        group = self.context.profiles.add_group(name)
        self._save_profiles()
        self._refresh_pages()
        self.toast(f"Группа добавлена: {name}")
        return group

    def update_group(self, group_id: int, *, name: str, url: str | None = None):
        """Rename a group and optionally change its subscription address."""
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return None

        group.name = name
        if url is not None:
            group.subscription_url = url
        self._save_profiles()
        self._refresh_pages()
        return group

    def delete_group(self, group_id: int) -> None:
        """Remove a group together with its profiles."""
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return

        name = group.name
        self.context.profiles.remove_group(group_id)
        self._save_profiles()
        self._refresh_pages()
        self.toast(f"Удалено: {name}")

    def save_profiles(self) -> None:
        """Persist the profile store after an external edit."""
        self._save_profiles()
        self._refresh_pages()

    def apply_settings(self) -> None:
        """Persist the configuration and push it into a running core."""
        try:
            self.context.save_config()
        except Exception as e:
            logger.warning("Could not persist settings: %s", e)
            self.toast(f"Не удалось сохранить настройки: {e}")
            return

        if not self.context.proxy_state.is_running:
            return

        result = self._ensure_connection_service().reload_config()
        if result.ok:
            self.toast("Настройки применены")
        else:
            self.toast(f"Настройки сохранены, но не применены: {result.error}")

    def _save_profiles(self) -> None:
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist profiles: %s", e)

    def _refresh_pages(self) -> None:
        if self._window is not None:
            self._window.refresh_pages()

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
        dialog.connect("closed", lambda _d: self._save_and_apply(dialog))
        self.present_dialog(dialog)

    def _save_and_apply(self, dialog) -> None:
        dialog.save()
        self.apply_settings()

    def _open_about(self) -> None:
        dialog = Adw.AboutDialog(
            application_name="Tenga Proxy",
            application_icon="network-server-symbolic",
            developer_name="Artem G.",
            version=app_version(),
            comments="Клиент прокси для Linux на базе xray-core",
            license_type=Gtk.License.MIT_X11,
        )
        self.present_dialog(dialog)

    def _open_shortcuts(self) -> None:
        from src.ui.shortcuts import ShortcutsDialog

        self.present_dialog(ShortcutsDialog())

    def wait_for_connection_for_test(self, timeout: float = 10.0) -> None:
        if self._connection_thread is not None:
            self._connection_thread.join(timeout)

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    # Действия страниц

    def set_latency_probe(self, probe: Callable[[int], int]) -> None:
        """Install the function measuring one profile's latency.

        Проба передаётся снаружи: она живёт на уровне ядра и требует запуска
        временного xray, а окно не должно знать об этом.
        """
        self._latency_probe = probe
        self._latency_runner = LatencyRunner(probe)

    def set_subscription_updater(self, updater: Callable[[int, str], int]) -> None:
        """Install the function refreshing one subscription group."""
        self._subscription_updater = updater

    def set_profile_activation_handler(self, handler: Callable[[int], None]) -> None:
        """Install what happens when a profile row is activated."""
        self._profile_activation_handler = handler

    def select_profile(self, profile_id: int) -> None:
        """Connect to a profile activated on the profiles page."""
        if self._profile_activation_handler is not None:
            self._profile_activation_handler(profile_id)
            return
        self.connect_profile(profile_id)

    def update_subscription(self, group_id: int) -> None:
        """Refresh one subscription group in the background."""
        group = self.context.profiles.get_group(group_id)
        if group is None or not group.subscription_url:
            self.toast("У подписки нет адреса")
            return

        updater = self._subscription_updater or self._default_subscription_updater
        url = group.subscription_url

        self.toast(f"Обновляю: {group.name}")
        self._subscriptions_thread = run_in_background(
            lambda: updater(group_id, url),
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            name="tenga-subscription",
        )

    def _default_latency_probe(self, profile_id: int) -> int:
        from src.core.config_builder import build_latency_probe_config
        from src.core.xray_manager import XrayManager

        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            return -1

        built = build_latency_probe_config(self.context, profile)
        if built is None:
            return -1

        config, socks_port = built
        manager = XrayManager(binary_path=self.context.xray_manager.binary_path)
        try:
            started, error = manager.start(config)
            if not started:
                logger.warning("Latency probe could not start xray: %s", error)
                return -1
            return manager.test_delay_realistic(
                proxy_address=self.context.config.inbound_address,
                proxy_port=socks_port,
            )
        finally:
            try:
                manager.stop()
            except Exception:
                logger.debug("Latency probe cleanup failed", exc_info=True)

    def _default_subscription_updater(self, group_id: int, url: str) -> int:
        from src.sub.updater import update_subscription

        beans = update_subscription(
            url,
            config=self.context.config,
            profiles=self.context.profiles,
            group_id=group_id,
        )
        return len(beans)

    def _ensure_latency_runner(self) -> LatencyRunner:
        if self._latency_runner is None:
            self._latency_runner = LatencyRunner(self._latency_probe or self._default_latency_probe)
        return self._latency_runner

    def _test_latency(self) -> None:
        profile_ids = list(self.context.profiles.profiles)
        if not profile_ids:
            self.toast("Нет профилей для проверки")
            return

        runner = self._ensure_latency_runner()
        started = runner.run(
            profile_ids,
            on_result=self._on_latency_result,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")
            return

        self.toast(f"Проверяю задержку: {len(profile_ids)} профилей")

    def test_latency_for(self, profile_id: int) -> None:
        """Measure the latency of one profile."""
        if self.context.profiles.get_profile(profile_id) is None:
            self.toast("Профиль не найден")
            return

        runner = self._ensure_latency_runner()
        started = runner.run(
            [profile_id],
            on_result=self._on_latency_result,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")

    def _on_latency_result(self, profile_id: int, latency_ms: int) -> None:
        profile = self.context.profiles.get_profile(profile_id)
        if profile is not None:
            profile.latency_ms = latency_ms

    def _on_latency_done(self) -> None:
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist latency results: %s", e)

        if self._window is not None:
            self._window.refresh_pages()
        self.toast("Проверка задержки завершена")

    def _refresh_subscriptions(self) -> None:
        groups = [
            group
            for group in self.context.profiles.groups.values()
            if group.is_subscription and group.subscription_url
        ]
        if not groups:
            self.toast("Подписок нет")
            return

        updater = self._subscription_updater or self._default_subscription_updater
        targets = [(group.id, group.subscription_url) for group in groups]

        def work() -> int:
            total = 0
            for group_id, url in targets:
                try:
                    total += updater(group_id, url)
                except Exception as e:
                    logger.warning("Subscription %s failed: %s", group_id, e)
            return total

        self.toast(f"Обновляю подписки: {len(targets)}")
        self._subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            name="tenga-subscriptions",
        )

    def _on_subscriptions_updated(self, total: int) -> None:
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist updated subscriptions: %s", e)

        if self._window is not None:
            self._window.refresh_pages()
        self.toast(f"Обновлено профилей: {total}")

    def _on_subscriptions_failed(self, error: BaseException) -> None:
        self.toast(f"Не удалось обновить подписки: {error}")

    def _toggle_search(self) -> None:
        if self._window is not None:
            self._window.search_button.set_active(not self._window.search_button.get_active())

    # Ожидание фоновых задач: только для тестов, в рабочем коде всё идёт
    # через главный цикл.

    def wait_for_latency_for_test(self, timeout: float = 10.0) -> None:
        from gi.repository import GLib

        if self._latency_runner is not None:
            self._latency_runner.wait(timeout)

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def wait_for_subscriptions_for_test(self, timeout: float = 10.0) -> None:
        from gi.repository import GLib

        if self._subscriptions_thread is not None:
            self._subscriptions_thread.join(timeout)

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
        self._latency_runner = None
        self._latency_probe = None
        self._subscription_updater = None
        self._subscriptions_thread = None
        self._profile_activation_handler = None
        self._connection_service = None
        self._connection_thread = None
        self._dialog = None
        self.last_toast_for_test = ""

    def toast(self, text: str) -> None:
        """Show a message in the window, if there is one."""
        # Последнее сообщение хранится и без окна: тосты — единственный
        # видимый результат многих действий, и тестам нужно их читать.
        self.last_toast_for_test = text
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


def run_app(config_dir=None, lock=None, with_tray: bool = True) -> int:
    """Entry point for the GTK4 interface."""
    from src.core.context import init_context

    context = init_context(config_dir=config_dir)
    app = TengaApplication(context=context, lock=lock, with_tray=with_tray)
    return app.run([])
