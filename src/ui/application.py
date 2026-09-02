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
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner
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

    def __init__(self, context: AppContext | None = None, lock=None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.context = context or get_context()
        self._lock = lock
        self._signal_source_ids: list[int] = []
        self._window: MainWindow | None = None
        self._latency_runner: LatencyRunner | None = None
        self._latency_probe: Callable[[int], int] | None = None
        self._subscription_updater: Callable[[int, str], int] | None = None
        self._subscriptions_thread = None
        self._profile_activation_handler: Callable[[int], None] | None = None

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
            "refresh-subscriptions": self._refresh_subscriptions,
            "test-latency": self._test_latency,
            "search": self._toggle_search,
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
        """Handle a profile activated on the profiles page.

        Подключение появится на этапе 3 вместе с диалогами; пока действие
        только сообщает выбор наружу.
        """
        if self._profile_activation_handler is not None:
            self._profile_activation_handler(profile_id)
            return

        profile = self.context.profiles.get_profile(profile_id)
        name = profile.name if profile is not None else str(profile_id)
        self.toast(f"Выбран профиль: {name}")

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
            self._latency_runner = LatencyRunner(
                self._latency_probe or self._default_latency_probe
            )
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
            self._window.search_button.set_active(
                not self._window.search_button.get_active()
            )

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

    def reset_for_tests(self, context: AppContext | None) -> None:
        """Rebind the application to another context and drop the window.

        Существует ради тестов: создать второе приложение нельзя, GApplication
        занимает путь на шине сессии до конца процесса.
        """
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
