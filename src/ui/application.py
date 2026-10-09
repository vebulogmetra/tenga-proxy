"""GTK4 + libadwaita application shell."""

from __future__ import annotations

import logging
import signal
import time
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from src.core.context import AppContext, get_context
from src.core.core_update import fetch_releases, is_check_due, refresh_known_releases
from src.core.failover import FailoverController
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner, make_batch_probe
from src.ui.logic.profiles_view import SortKey
from src.ui.logic.status import ConnectionState
from src.ui.logic.subscriptions_view import describe_update_error, describe_url_change
from src.ui.logic.version import app_version, core_version
from src.ui.window import APP_ICON, MainWindow, load_css, load_icons

# Шаг склейки перерисовок на время замера задержки.
LATENCY_REFRESH_INTERVAL_MS = 150

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
        self._latency_refresh_id: int | None = None
        self._latency_probe: Callable[[int], int] | None = None
        self._subscription_updater: Callable[[int, str], int] | None = None
        self._subscriptions_thread = None
        # Предложения сменить адрес подписки: копятся в фоновом потоке,
        # показываются в главном, по одному и только с подтверждением.
        self._url_proposals: list = []
        self._profile_activation_handler: Callable[[int], None] | None = None
        self._connection_service = None
        self._connection_thread = None
        self._dialog = None
        self._failover: FailoverController | None = None
        self._release_fetcher: Callable[[], object] | None = None
        self._core_update_thread = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""

    # Жизненный цикл

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_icons()
        load_css()
        self._register_actions()
        self._setup_signal_handlers()
        self.watch_monitor()
        if self._with_tray:
            self.start_tray()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(application=self, context=self.context)
        self._window.present()
        self.resume_monitoring()
        self._refresh_core_releases_if_due()

    def resume_monitoring(self) -> None:
        """Start watching a proxy that is already running.

        Наблюдение запускает подключение, но приложение может открыться при
        уже поднятом прокси — тогда проверки не шли бы вовсе, и страница
        мониторинга показывала бы «Недоступен» при работающем соединении.
        """
        monitor = self.context.monitor
        if monitor is None or not self.context.proxy_state.is_running:
            return
        monitor.start()

    def set_release_fetcher(self, fetch: Callable[[], object] | None) -> None:
        """Install the function asking GitHub about core releases.

        Без неё приложение в сеть за релизами не ходит: её ставит только
        `run_app`, поэтому тесты и встраивание остаются без сетевых запросов.
        """
        self._release_fetcher = fetch

    def _refresh_core_releases_if_due(self) -> None:
        """Remember the newest core releases, at most once in a few days.

        Только запоминает: о новой версии говорит страница «О программе».
        """
        fetch = self._release_fetcher
        config = self.context.config
        if fetch is None or not is_check_due(config, time.time()):
            return
        if self._core_update_thread is not None and self._core_update_thread.is_alive():
            return

        self._core_update_thread = run_in_background(
            lambda: refresh_known_releases(config, now=time.time(), fetch=fetch),
            on_done=lambda _releases: self.context.save_config(),
            # Нет сети — спросим при следующем запуске.
            on_error=lambda _error: None,
            name="tenga-core-update",
        )

    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
        if self._core_update_thread is not None:
            self._core_update_thread.join(timeout)

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def watch_monitor(self) -> None:
        """Hand the monitor's verdicts to the failover controller.

        Контроллер сам смотрит в настройки и при выключенном автопереключении
        ничего не делает, поэтому подписка ставится безусловно.
        """
        monitor = self.context.monitor
        if monitor is None:
            return

        self._failover = FailoverController(
            self.context,
            switch_to=self.connect_profile,
            notify=self.notify_user,
            network_available=_network_available,
        )
        monitor.set_on_status_changed(self._failover.handle_status)

    def notify_user(self, text: str) -> None:
        """Tell the user something they must not miss.

        Тост виден только в открытом окне, а приложение обычно свёрнуто в
        трей — поэтому сообщение дублируется уведомлением рабочего стола.
        """
        self.last_notification_for_test = text
        self.toast(text)

        notification = Gio.Notification.new("Tenga Proxy")
        notification.set_body(text)
        self.send_notification(FAILOVER_NOTIFICATION_ID, notification)

    def do_shutdown(self) -> None:
        # Выход по SIGTERM не эмитирует close-request, поэтому геометрия
        # сохраняется здесь: этот путь общий для всех способов завершения.
        if self._window is not None:
            self._window.save_geometry()

        # Ядро гасится до снятия блокировки: иначе следующий экземпляр
        # запустится, пока этот ещё держит TUN-интерфейс.
        if self._connection_service is not None:
            self._connection_service.shutdown(self._connection_thread)

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
            on_done=lambda result: self._on_connection_done(result, profile_id, profile.name),
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
            # Трей и кнопка в окне без выделения подключают последний профиль.
            last = self.context.profiles.last_used_profile()
            profile_id = None if last is None else last.id
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

    def _on_connection_done(self, result, profile_id: int, profile_name: str) -> None:
        if result.ok:
            self.context.profiles.mark_used(profile_id)
            self._save_profiles()
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
        core = core_version(getattr(self.context, "xray_manager", None))
        dialog = Adw.AboutDialog(
            application_name="Tenga Proxy",
            application_icon=APP_ICON,
            developer_name="Artem G.",
            version=app_version(),
            comments=f"Клиент прокси для Linux на базе xray-core {core}",
            website="https://github.com/vebulogmetra/tenga-proxy",
            license_type=Gtk.License.MIT_X11,
        )
        # Строку целиком копируют в отчёт об ошибке, поэтому обе версии рядом.
        dialog.set_debug_info(f"Tenga Proxy {app_version()}\nxray-core {core}")
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

        def work() -> int:
            try:
                return updater(group_id, url)
            except Exception:
                self._propose_fallback_url(group_id, url)
                raise

        self.toast(f"Обновляю: {group.name}")
        self._subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            name="tenga-subscription",
        )

    def _default_subscription_updater(self, group_id: int, url: str) -> int:
        from src.sub.route import local_proxy_url
        from src.sub.updater import SubscriptionUpdater
        from src.sub.url_change import REASON_NEW_URL, propose_url_change

        context = self.context
        updater = SubscriptionUpdater(
            config=context.config,
            profiles=context.profiles,
            proxy_url=lambda: local_proxy_url(context.config, context.proxy_state),
        )
        beans = updater.update(url, group_id)

        proposal = propose_url_change(group_id, url, updater.new_url, REASON_NEW_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)
        return len(beans)

    def _propose_fallback_url(self, group_id: int, url: str) -> None:
        """Queue the provider's fallback address after a failed update."""
        from src.sub.url_change import REASON_FALLBACK_URL, propose_url_change

        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        proposal = propose_url_change(group_id, url, group.sub_fallback_url, REASON_FALLBACK_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)

    def _offer_url_change(self) -> None:
        """Ask about one queued address change; the rest come back with the next update."""
        if not self._url_proposals:
            return
        proposal = self._url_proposals[0]
        self._url_proposals.clear()

        group = self.context.profiles.get_group(proposal.group_id)
        if group is None or self._window is None:
            return

        from src.ui.dialogs.confirm import build_url_change_confirmation

        heading, body = describe_url_change(group.name, group.subscription_url, proposal)
        self.present_dialog(
            build_url_change_confirmation(heading, body, lambda: self._apply_url_change(proposal))
        )

    def _apply_url_change(self, proposal) -> None:
        """Switch the subscription to the confirmed address and refresh it."""
        group = self.context.profiles.get_group(proposal.group_id)
        if group is None:
            return
        self.update_group(proposal.group_id, name=group.name, url=proposal.new_url)
        self.update_subscription(proposal.group_id)

    def _ensure_latency_runner(self) -> LatencyRunner:
        if self._latency_runner is None:
            if self._latency_probe is not None:
                self._latency_runner = LatencyRunner(self._latency_probe)
            else:
                # Весь набор меряет один временный процесс ядра.
                self._latency_runner = LatencyRunner(batch_probe=make_batch_probe(self.context))
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

    def test_latency_for_group(self, group_id: int) -> None:
        """Measure the latency of one group, ordering rows as results arrive."""
        store = self.context.profiles
        if store.get_group(group_id) is None:
            self.toast("Группа не найдена")
            return

        profile_ids = [profile.id for profile in store.get_profiles_in_group(group_id)]
        if not profile_ids:
            self.toast("В группе нет профилей")
            return

        # Пинг группы — единственный случай, когда порядок строк говорит о
        # результате: список пересортировывается по задержке, пока идёт замер.
        if self._window is not None:
            self._window.profiles_page.set_sort(SortKey.PING, ascending=True)

        runner = self._ensure_latency_runner()
        started = runner.run(
            profile_ids,
            on_result=self._on_latency_result_live,
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

    def _on_latency_result_live(self, profile_id: int, latency_ms: int) -> None:
        """Store one result and schedule a re-sort of the list.

        Перерисовка склеивается по таймеру: список должен пересортировываться
        по ходу замера, но на группе в сотни профилей построчный refresh занял
        бы секунды главного цикла и превратил бы обновление в рывки.
        """
        self._on_latency_result(profile_id, latency_ms)
        self._schedule_latency_refresh()

    def _schedule_latency_refresh(self) -> None:
        if self._window is None or self._latency_refresh_id is not None:
            return

        def _redraw() -> bool:
            self._latency_refresh_id = None
            if self._window is not None:
                self._window.refresh_pages()
            return GLib.SOURCE_REMOVE

        self._latency_refresh_id = GLib.timeout_add(LATENCY_REFRESH_INTERVAL_MS, _redraw)

    def _cancel_latency_refresh(self) -> None:
        if self._latency_refresh_id is not None:
            GLib.source_remove(self._latency_refresh_id)
            self._latency_refresh_id = None

    def _on_latency_done(self) -> None:
        # Итоговая перерисовка всё равно будет ниже: отложенная только
        # продублировала бы её уже после сохранения.
        self._cancel_latency_refresh()
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
                    logger.warning("Subscription %s failed: %s", group_id, describe_update_error(e))
                    self._propose_fallback_url(group_id, url)
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
        self._offer_url_change()

    def _on_subscriptions_failed(self, error: BaseException) -> None:
        sent = self.context.config.sub_send_device_info
        reason = describe_update_error(error, device_info_sent=sent)
        self.toast(f"Не удалось обновить подписки: {reason}")
        self._offer_url_change()

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
        self._url_proposals = []
        self._profile_activation_handler = None
        self._connection_service = None
        self._connection_thread = None
        self._dialog = None
        self._failover = None
        self._release_fetcher = None
        self._core_update_thread = None
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""

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
    from src.core.monitor import attach_monitor

    context = init_context(config_dir=config_dir)
    # Монитор заводится здесь: без него страница мониторинга пуста, а
    # подключение не начинает наблюдение — `ConnectionService` запускает уже
    # готовый монитор, но сам его не создаёт.
    attach_monitor(context)
    app = TengaApplication(context=context, lock=lock, with_tray=with_tray)
    app.set_release_fetcher(fetch_releases)
    return app.run([])
