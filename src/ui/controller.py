"""Оркестровка приложения без GTK.

`AppController` держит всё, что не является виджетом: подключение, данные,
подписки, замер задержки, failover, проверку обновлений, импорт ссылок.
С интерфейсом он говорит через `Shell`, с главным потоком — через `MainLoop`,
поэтому один контроллер обслуживает GTK на Linux и Qt на Windows
(docs/plans/2026-10-28-windows-qt-frontend-design.md).

Поведение перенесено из `TengaApplication` один в один: тексты сообщений,
порядок обновления окна и проверки занятости — часть контракта, который
закрепляют GTK-тесты.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from src import __app_name__
from src.core.core_pid import take_block_released
from src.core.core_update import is_check_due, refresh_known_releases
from src.core.failover import FailoverController
from src.diag.assess import recommendations as rec
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner, PingProgress, make_batch_probe
from src.ui.logic.status import BLOCKED_BANNER, ConnectionState, is_traffic_blocked
from src.ui.logic.subscriptions_view import describe_update_error, describe_url_change
from src.ui.logic.version import app_version

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.core.main_loop import MainLoop
    from src.ui.logic.diagnostics_session import DiagnosticsSession

logger = logging.getLogger("tenga.ui.controller")

# Шаг склейки перерисовок на время замера задержки.
LATENCY_REFRESH_INTERVAL_MS = 150

# Виды подтверждений: оболочка выбирает по ним кнопки и их внешний вид.
CONFIRM_DELETE = "delete"
CONFIRM_URL_CHANGE = "url-change"
SETTINGS_DNS = "dns"

CORE_EXIT_RESTART = "Ядро остановилось, переподключаюсь"
CORE_EXIT_GAVE_UP = "Ядро остановилось, трафик идёт напрямую"
BLOCK_RELEASED = "Блокировка снята"
BLOCK_RELEASED_AFTER_CRASH = "Прошлый сеанс завершился сбоем, блокировка трафика снята"
# Ядро, падающее снова сразу после перезапуска, перезапускать бесполезно.
CORE_RESTART_COOLDOWN = 60.0
VPN_WATCH_INTERVAL_MS = 5000


@dataclass(frozen=True)
class UpdateOutcome:
    """Итог обновления одной подписки: число серверов и предложения провайдера."""

    count: int
    new_url: str = ""
    fallback_used: str = ""
    routing_link: str = ""


class Shell(Protocol):
    """Что контроллеру нужно от интерфейса. Реализуют GTK- и Qt-оболочки.

    Методы, зависящие от окна, при закрытом окне ничего не делают — это
    забота реализации, контроллер их зовёт безусловно.
    """

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None: ...

    def notify(self, text: str) -> None:
        """Системное уведомление: видно и при свёрнутом окне."""

    def has_window(self) -> bool: ...

    def refresh_status(self) -> None: ...

    def refresh_pages(self) -> None: ...

    def show_connecting(self, profile_name: str) -> None: ...

    def show_error(self, message: str) -> None: ...

    def selected_profile_id(self) -> int | None: ...

    def sort_by_ping(self) -> None: ...

    def set_ping_progress(self, progress: PingProgress | None) -> None: ...

    def update_group_progress(self, group_id: int) -> None: ...

    def set_tray_state(self, state: ConnectionState, profile_name: str) -> None: ...

    def set_action_enabled(self, name: str, enabled: bool) -> None: ...

    def confirm(
        self,
        kind: str,
        heading: str,
        body: str,
        on_confirm: Callable[[], None],
        *,
        confirm_label: str | None = None,
    ) -> None: ...

    def open_subscription_form(self, name: str, url: str) -> None: ...

    def open_routing_import(
        self,
        rows: list,
        on_confirm: Callable[[], None],
        on_dismiss: Callable[[], None] | None = None,
    ) -> None:
        """Окно подтверждения импорта; `on_dismiss` — закрыли без применения."""

    def show_network_diagnostics(self, session: DiagnosticsSession) -> None:
        """Открыть окно диагностики или поднять уже открытое."""

    def open_settings_section(self, section: str) -> None:
        """Открыть настройки на разделе; пока раздел один — `SETTINGS_DNS`."""

    def activate_window(self) -> None: ...


def resume_monitoring(context: Any) -> None:
    """Start watching a proxy that is already running.

    Наблюдение запускает подключение, но приложение может открыться при
    уже поднятом прокси — тогда проверки не шли бы вовсе, и страница
    мониторинга показывала бы «Недоступен» при работающем соединении.
    """
    monitor = context.monitor
    if monitor is None or not context.proxy_state.is_running:
        return
    monitor.start()


class AppController:
    """Оркестровка приложения; окно, трей и диалоги — за `Shell`."""

    def __init__(
        self,
        context: AppContext,
        shell: Shell,
        loop: MainLoop,
        *,
        network_available: Callable[[], bool] = lambda: True,
        app_version: Callable[[], str] = app_version,
    ) -> None:
        self.context = context
        self._shell = shell
        self._loop = loop
        self._network_available = network_available
        # Вызываемый объект, а не строка: GTK-тесты подменяют `app_version`
        # в модуле приложения, и подмена должна действовать здесь.
        self._app_version = app_version

        # Потоки и раннер публичные: приложение ждёт их в тестовых помощниках.
        self.latency_runner: LatencyRunner | None = None
        self._latency_probe: Callable[[int], int] | None = None
        self._latency_refresh_handle: object | None = None
        self._ping_progress: PingProgress | None = None
        self._subscription_updater: Callable[[int, str], int] | None = None
        self.subscriptions_thread = None
        self._subscription_busy = False
        # Предложения сменить адрес подписки: копятся в фоновом потоке,
        # показываются в главном, по одному и только с подтверждением.
        self._url_proposals: list = []
        # Наборы маршрутов из заголовка `routing`: (группа, AppLink).
        self._routing_proposals: list = []
        self._profile_activation_handler: Callable[[int], None] | None = None
        self._connection_service = None
        self.connection_thread = None
        self._failover: FailoverController | None = None
        self._core_exit_at: float | None = None
        self._vpn_watch: object | None = None
        self.vpn_probe_thread = None
        self._vpn_probe_running = False
        self._core_exit_pending = False
        self._release_fetcher: Callable[[], object] | None = None
        self.core_update_thread = None
        self.app_update_thread = None
        self._app_release_fetcher = None
        self._diagnostics: DiagnosticsSession | None = None

    # --- сообщения ---

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._shell.toast(text, button=button, action=action)

    def notify_user(self, text: str) -> None:
        """Tell the user something they must not miss.

        Тост виден только в открытом окне, а приложение обычно свёрнуто в
        трей — поэтому сообщение дублируется уведомлением рабочего стола.
        """
        self._shell.toast(text)
        self._shell.notify(text)

    # --- жизненный цикл ---

    def resume_monitoring(self) -> None:
        resume_monitoring(self.context)

    def shutdown(self) -> None:
        """Погасить ядро: вызывается до снятия блокировки экземпляра."""
        if self._diagnostics is not None:
            self._diagnostics.close()
        if self._vpn_watch is not None:
            self._loop.cancel(self._vpn_watch)
            self._vpn_watch = None
        if self._connection_service is not None:
            self._connection_service.shutdown(self.connection_thread)

    # --- диагностика сети ---

    def open_network_diagnostics(self) -> None:
        """Сессия одна на приложение: повторное открытие показывает прежние результаты."""
        if self._diagnostics is None:
            from src.diag.runner import context_sources, desktop_runner
            from src.ui.logic.diagnostics_session import DiagnosticsSession

            sources = context_sources(self.context)
            self._diagnostics = DiagnosticsSession(
                self._loop, lambda: desktop_runner(sources, self._app_version())
            )
        self._shell.show_network_diagnostics(self._diagnostics)

    def run_recommendation(self, code: str) -> None:
        """Действие выполняется только по кнопке: сама проверка настроек не меняет."""
        if code == rec.CHECK_SYSTEM_DNS:
            self._shell.open_settings_section(SETTINGS_DNS)
        elif code == rec.USE_ACTIVE_VPN:
            if self.context.proxy_state.is_running:
                self.toast(f"{__app_name__} уже подключён")
            else:
                self.connect_selected()
        elif code == rec.TRY_OTHER_PROFILE:
            self._shell.activate_window()
        elif code in (rec.CHECK_SYSTEM_NETWORK, rec.OPEN_WIFI_LOGIN):
            self.toast("Проверьте подключение к сети и повторите проверку")
        elif self._diagnostics is not None and not self._diagnostics.start():
            self.toast("Проверка уже идёт")

    # --- данные ---

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        """Store a parsed profile and persist it."""
        entry = self.context.profiles.add_profile(bean, group_id=group_id)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Сервер добавлен: {entry.name}")
        return entry

    def delete_profile(self, profile_id: int) -> None:
        """Remove one profile."""
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Сервер не найден")
            return

        name = profile.name
        self.context.profiles.remove_profile(profile_id)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Сервер удалён: {name}")

    def add_group(self, name: str):
        """Create a plain group."""
        group = self.context.profiles.add_group(name)
        self._save_profiles()
        self._shell.refresh_pages()
        self.toast(f"Группа добавлена: {name}")
        return group

    def update_group(self, group_id: int, *, name: str, url: str | None = None):
        """Rename a group and optionally change its subscription address."""
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return None

        group.name = name
        if url is not None and url != group.subscription_url:
            group.subscription_url = url
            # Запасной адрес относился к прежнему: при смене провайдера его сбой
            # молча подтянул бы серверы старой подписки с её токеном.
            group.sub_fallback_url = ""
            group.sub_via_fallback = False
        self._save_profiles()
        self._shell.refresh_pages()
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
        self._shell.refresh_pages()
        self.toast(f"Удалено: {name}")

    def save_profiles(self) -> None:
        """Persist the profile store after an external edit."""
        self._save_profiles()
        self._shell.refresh_pages()
        self._shell.refresh_status()

    def _save_profiles(self) -> None:
        try:
            if not self.context.save_profiles():
                raise OSError("Запись серверов не выполнена")
        except Exception as e:
            logger.warning("Could not persist profiles: %s", e)
            self.toast("Не удалось сохранить серверы")

    # --- настройки и маршрутизация ---

    def apply_settings(self) -> bool:
        """Persist settings; runtime changes await an explicit reconnect."""
        try:
            if not self.context.save_config():
                raise OSError("Запись настроек не выполнена")
        except Exception as error:
            logger.warning("Could not persist settings: %s", error)
            self.toast("Не удалось сохранить настройки")
            return False
        monitor = self.context.monitor
        if monitor is not None and self.context.proxy_state.is_running:
            monitor.stop()
            monitor.start()
        self._shell.refresh_status()
        return True

    def apply_routing_import(self, routing) -> None:
        from src.ui.logic.routing_import import apply_import

        apply_import(self.context.config, routing, self.context.config_dir)
        if self.apply_settings():
            self.sync_restore_routing()
            self.toast(
                "Маршрутизация импортирована", button="Вернуть", action="app.restore-routing"
            )

    def restore_routing(self) -> None:
        """Вернуть общую маршрутизацию до последнего импорта ссылкой."""
        from src.ui.logic.routing_import import restore_backup

        if not restore_backup(self.context.config):
            return
        if self.apply_settings():
            self.toast("Маршрутизация до импорта возвращена")
        self.sync_restore_routing()

    def sync_restore_routing(self) -> None:
        self._shell.set_action_enabled(
            "restore-routing", self.context.config.routing_backup is not None
        )

    # --- подключение ---

    def set_connection_service(self, service) -> None:
        """Install the object starting and stopping the proxy."""
        self._connection_service = service

    def _ensure_connection_service(self):
        if self._connection_service is None:
            from src.core.connection import ConnectionService

            self._connection_service = ConnectionService(self.context)
        return self._connection_service

    def connection_busy(self) -> bool:
        return self.connection_thread is not None and self.connection_thread.is_alive()

    def connect_profile(self, profile_id: int) -> None:
        """Start the proxy for one profile in the background."""
        if self.latency_runner is not None and self.latency_runner.is_busy:
            self.toast("Дождитесь завершения проверки задержки")
            return
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Сервер не найден")
            return

        if self.connection_busy():
            # Два одновременных запуска оставили бы висящий процесс xray.
            self.toast("Подключение уже выполняется")
            return

        self._shell.show_connecting(profile.name)
        # Промежуточное состояние живёт только в UI: в proxy_state его нет,
        # и сам по себе трей о нём не узнает.
        self._shell.set_tray_state(ConnectionState.CONNECTING, profile.name)

        self._watch_core()
        self._watch_vpn_interface()
        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            lambda: service.connect(profile_id),
            on_done=lambda result: self._on_connection_done(result, profile_id, profile.name),
            on_error=self._on_connection_failed,
            dispatch=self._loop.dispatch,
            name="tenga-connect",
        )

    def disconnect_proxy(self) -> None:
        """Stop the proxy in the background."""
        if self.connection_busy():
            self.toast("Подключение уже выполняется")
            return

        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            service.disconnect,
            on_done=lambda result: self._on_disconnection_done(result),
            on_error=self._on_connection_failed,
            dispatch=self._loop.dispatch,
            name="tenga-disconnect",
        )

    def connect_selected(self) -> None:
        profile_id = self._shell.selected_profile_id()
        if profile_id is None:
            # Трей и кнопка в окне без выделения подключают последний профиль.
            last = self.context.profiles.last_used_profile()
            profile_id = None if last is None else last.id
        if profile_id is None:
            self.toast("Выберите сервер в списке")
            return
        self.connect_profile(profile_id)

    def toggle_connection(self) -> None:
        state = self.context.proxy_state
        if state.is_running:
            self.disconnect_proxy()
            return
        # Случайный клик не должен открыть трафик и увести на другой сервер.
        if is_traffic_blocked(state) and self.context.profiles.get_profile(
            state.blocked_profile_id
        ):
            self.connect_profile(state.blocked_profile_id)
            return
        self.connect_selected()

    def release_block(self) -> None:
        """Снять блокировку трафика, оставшуюся без сеанса."""
        if self.connection_busy():
            self.toast("Подключение уже выполняется")
            return
        service = self._ensure_connection_service()
        self.connection_thread = run_in_background(
            service.release_block,
            on_done=lambda _result: self._on_block_released(),
            on_error=self._on_connection_failed,
            dispatch=self._loop.dispatch,
            name="tenga-release-block",
        )

    def _on_block_released(self) -> None:
        self.toast(BLOCK_RELEASED)
        self._shell.set_tray_state(ConnectionState.DISCONNECTED, "")
        self._refresh_window()
        self._settle_core_exit()

    def report_recovery(self) -> None:
        """Сказать о блокировке, которую при старте пришлось снять за упавшим сеансом."""
        if take_block_released():
            self.notify_user(BLOCK_RELEASED_AFTER_CRASH)

    def _show_failure_in_tray(self) -> None:
        state = self.context.proxy_state
        if is_traffic_blocked(state):
            self.notify_user(BLOCKED_BANNER)
            profile = self.context.profiles.get_profile(state.blocked_profile_id)
            self._shell.set_tray_state(ConnectionState.BLOCKED, profile.name if profile else "")
        else:
            self._shell.set_tray_state(ConnectionState.ERROR, "")

    def reconnect_current(self) -> None:
        state = self.context.proxy_state
        if state.is_running:
            self.connect_profile(state.started_profile_id)

    def set_profile_activation_handler(self, handler: Callable[[int], None]) -> None:
        """Install what happens when a profile row is activated."""
        self._profile_activation_handler = handler

    def select_profile(self, profile_id: int) -> None:
        """Connect to a profile activated on the profiles page."""
        if self._profile_activation_handler is not None:
            self._profile_activation_handler(profile_id)
            return
        self.connect_profile(profile_id)

    def _on_connection_done(self, result, profile_id: int, profile_name: str) -> None:
        if result.ok:
            self.context.profiles.mark_used(profile_id)
            self._save_profiles()
            self.toast(f"Подключено: {profile_name}")
            if result.warning:
                self.toast(result.warning)
        else:
            self.toast(f"Не удалось подключиться: {result.error}")
            self._shell.show_error(result.error)
            self._show_failure_in_tray()

        self._refresh_window()
        self._settle_core_exit()

    def _on_disconnection_done(self, result) -> None:
        if result.ok:
            self.toast("Отключено")
            self._shell.set_tray_state(ConnectionState.DISCONNECTED, "")
        else:
            self.toast(f"Не удалось отключиться: {result.error}")
        self._refresh_window()
        self._settle_core_exit()

    def _on_connection_failed(self, error: BaseException) -> None:
        self.toast(f"Ошибка подключения: {error}")
        self._shell.show_error(str(error))
        self._show_failure_in_tray()
        self._refresh_window()
        self._settle_core_exit()

    def _refresh_window(self) -> None:
        self._shell.refresh_status()
        self._shell.refresh_pages()

    # --- интерфейс VPN ---

    def _watch_vpn_interface(self) -> None:
        if self._vpn_watch is None:
            self._vpn_watch = self._loop.schedule(VPN_WATCH_INTERVAL_MS, self._check_vpn_interface)

    def _check_vpn_interface(self) -> bool:
        """VPN переподключился на другой интерфейс: таблица закрывала бы его самого."""
        if self._vpn_probe_running or self.connection_busy():
            return True
        service = self._ensure_connection_service()
        name = service.watched_vpn()
        if name is None:
            return True
        self._vpn_probe_running = True
        self.vpn_probe_thread = run_in_background(
            lambda: service.probe_vpn_interface(name),
            on_done=lambda interface: self._on_vpn_interface(name, interface),
            on_error=lambda _error: self._on_vpn_interface(name, None),
            dispatch=self._loop.dispatch,
            name="tenga-vpn-interface",
        )
        return True

    def _on_vpn_interface(self, name: str, interface: str | None) -> None:
        self._vpn_probe_running = False
        if interface is None or self.connection_busy():
            return
        if self._ensure_connection_service().follow_vpn_interface(name, interface):
            # Исходящее соединение ядра привязано к старому имени.
            self.reconnect_current()

    # --- падение ядра ---

    def _watch_core(self) -> None:
        """Подписаться на самостоятельный выход ядра; сигнал приходит из его потока."""
        try:
            manager = self.context.xray_manager
        except RuntimeError:
            # Ядра нет: об этом скажет само подключение.
            logger.debug("xray-core is not available yet", exc_info=True)
            return
        manager.set_on_unexpected_exit(lambda: self._loop.dispatch(self._on_core_exit))

    def _on_core_exit(self) -> None:
        if self.connection_busy():
            # Поток подключения ещё работает: разберёмся, когда он закончит.
            self._core_exit_pending = True
            return
        self._handle_core_exit()

    def _settle_core_exit(self) -> None:
        """Разобрать отложенный сигнал; зовётся из итога подключения или отключения."""
        if not self._core_exit_pending:
            return
        # Итог уже доставлен, но поток может ещё не выйти: занятым он больше не считается.
        self.connection_thread = None
        self._handle_core_exit()

    def _handle_core_exit(self) -> None:
        self._core_exit_pending = False
        if self.context.xray_manager.is_running:
            # Пока сигнал шёл, ядро подняли заново: упало уже не оно.
            return
        profile_id = self._ensure_connection_service().handle_core_exit()
        self._refresh_window()
        if profile_id < 0:
            return
        now = time.monotonic()
        if self._core_exit_at is not None and now - self._core_exit_at < CORE_RESTART_COOLDOWN:
            if is_traffic_blocked(self.context.proxy_state):
                self._show_failure_in_tray()
                self._refresh_window()
                return
            self._ensure_connection_service().release_block()
            self.notify_user(CORE_EXIT_GAVE_UP)
            self._shell.show_error(CORE_EXIT_GAVE_UP)
            self._shell.set_tray_state(ConnectionState.ERROR, "")
            return
        self._core_exit_at = now
        self.notify_user(CORE_EXIT_RESTART)
        self.connect_profile(profile_id)

    # --- failover ---

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
            network_available=self._network_available,
        )
        monitor.set_on_status_changed(self._failover.handle_status)

    # --- подписки ---

    def set_subscription_updater(self, updater: Callable[[int, str], UpdateOutcome | int]) -> None:
        """Install the function refreshing one subscription group."""
        self._subscription_updater = updater

    def add_subscription(self, name: str, url: str):
        """Create a subscription group and fetch it right away."""
        try:
            group = self.context.profiles.find_subscription_group(
                url, exceptions=self.context.config.sub_source_exceptions
            )
        except RuntimeError as error:
            self.toast(str(error))
            return None
        if group is not None:
            self.context.profiles.current_group_id = group.id
            self._shell.refresh_pages()
            self.update_subscription(group.id)
            return group
        group = self.context.profiles.add_group(name, is_subscription=True)
        group.subscription_url = url
        self._save_profiles()
        self._shell.refresh_pages()
        self.update_subscription(group.id)
        return group

    def update_subscription(self, group_id: int) -> None:
        """Refresh one subscription group in the background."""
        if self._subscription_busy or (
            self.latency_runner is not None and self.latency_runner.is_busy
        ):
            self.toast("Обновление подписок или проверка задержки уже выполняется")
            return
        group = self.context.profiles.get_group(group_id)
        if group is None or not group.subscription_url:
            self.toast("У подписки нет адреса")
            return

        updater = self._subscription_updater or self.default_subscription_updater
        url = group.subscription_url

        def work() -> int:
            try:
                return self._collect_outcome(group_id, url, updater(group_id, url))
            except Exception as error:
                self._propose_fallback_url(group_id, url, error)
                raise

        self._subscription_busy = True
        self.toast(f"Обновляю: {group.name}")
        self.subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            dispatch=self._loop.dispatch,
            name="tenga-subscription",
        )

    def default_subscription_updater(self, group_id: int, url: str) -> UpdateOutcome:
        from src.sub.route import local_proxy_url
        from src.sub.updater import SubscriptionUpdater

        context = self.context
        updater = SubscriptionUpdater(
            config=context.config,
            profiles=context.profiles,
            proxy_url=lambda: local_proxy_url(context.config, context.proxy_state),
        )
        beans = updater.update(url, group_id)
        return UpdateOutcome(
            len(beans),
            new_url=updater.new_url,
            fallback_used=updater.used_fallback_url,
            routing_link=updater.routing_link,
        )

    def _collect_outcome(self, group_id: int, url: str, outcome: UpdateOutcome | int) -> int:
        """Поставить в очередь предложения провайдера; вернуть число серверов.

        Зовётся из фонового потока: окна показывает `_offer_proposals`.
        """
        from src.sub.url_change import REASON_FALLBACK_USED, REASON_NEW_URL, propose_url_change

        if isinstance(outcome, int):
            return outcome
        # Очередь показывает одно предложение: прямое указание провайдера важнее.
        for candidate, reason in (
            (outcome.new_url, REASON_NEW_URL),
            (outcome.fallback_used, REASON_FALLBACK_USED),
        ):
            proposal = propose_url_change(group_id, url, candidate, reason)
            if proposal is not None:
                self._url_proposals.append(proposal)
        if outcome.routing_link:
            self._propose_routing(group_id, outcome.routing_link)
        return outcome.count

    def _propose_routing(self, group_id: int, raw: str) -> None:
        """Запомнить набор маршрутов из заголовка; показ — в главном потоке."""
        from src.fmt.app_links import parse_subscription_routing

        try:
            link = parse_subscription_routing(raw)
        except ValueError as error:
            logger.warning("Subscription %s routing header rejected: %s", group_id, error)
            return
        group = self.context.profiles.get_group(group_id)
        if group is None or group.sub_routing_handled == link.payload_hash:
            return
        self._routing_proposals.append((group_id, link))

    def _propose_fallback_url(self, group_id: int, url: str, error: BaseException) -> None:
        """Queue the provider's fallback address after a failed update."""
        from src.sub.fallback import can_propose_after
        from src.sub.url_change import REASON_FALLBACK_URL, propose_url_change

        if not can_propose_after(error):
            return
        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        proposal = propose_url_change(group_id, url, group.sub_fallback_url, REASON_FALLBACK_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)

    def _offer_proposals(self) -> None:
        """Одно окно за обновление: смена адреса раньше маршрутизации."""
        if self._url_proposals:
            self._offer_url_change()
            # Набор не помечен обработанным: вернётся со следующим обновлением.
            self._routing_proposals.clear()
            return
        self._offer_routing()

    def _offer_routing(self) -> None:
        if not self._routing_proposals:
            return
        group_id, link = self._routing_proposals[0]
        self._routing_proposals.clear()
        group = self.context.profiles.get_group(group_id)
        if group is None or not self._shell.has_window():
            return
        from src.ui.logic.routing_import import (
            effective_routing,
            import_rows,
            reset_routing,
            reset_rows,
            routing_differs,
        )

        current = effective_routing(self.context.config.routing, self.context.config_dir)
        target = reset_routing(current) if link.operation == "routing_off" else link.routing
        if not routing_differs(current, target):
            # Набор ничего не меняет (например, пустые списки или off при каждом
            # обновлении) — не спрашиваем, но и повторно не предлагаем.
            self._mark_routing_handled(group_id, link.payload_hash)
            return
        if link.operation == "routing_off":
            rows = reset_rows(current, subscription=group.name)
        else:
            rows = import_rows(
                current,
                target,
                name=link.name,
                direct_default=link.direct_default,
                subscription=group.name,
            )

        def confirm() -> None:
            self.apply_routing_import(target)
            self._mark_routing_handled(group_id, link.payload_hash)

        self._shell.open_routing_import(
            rows,
            confirm,
            on_dismiss=lambda: self._mark_routing_handled(group_id, link.payload_hash),
        )

    def _mark_routing_handled(self, group_id: int, payload_hash: str) -> None:
        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        group.sub_routing_handled = payload_hash
        self._save_profiles()

    def _offer_url_change(self) -> None:
        """Ask about one queued address change; the rest come back with the next update."""
        if not self._url_proposals:
            return
        proposal = self._url_proposals[0]
        self._url_proposals.clear()

        group = self.context.profiles.get_group(proposal.group_id)
        if group is None or not self._shell.has_window():
            return

        heading, body = describe_url_change(group.name, group.subscription_url, proposal)
        self._shell.confirm(
            CONFIRM_URL_CHANGE, heading, body, lambda: self._apply_url_change(proposal)
        )

    def _apply_url_change(self, proposal) -> None:
        """Switch the subscription to the confirmed address and refresh it."""
        group = self.context.profiles.get_group(proposal.group_id)
        if group is None:
            return
        try:
            collision = self.context.profiles.find_subscription_group(
                proposal.new_url, exceptions=self.context.config.sub_source_exceptions
            )
        except RuntimeError as error:
            self.toast(str(error))
            return
        if collision is not None and collision.id != group.id:
            self.toast("Этот адрес уже используется другой подпиской")
            return
        self.update_group(proposal.group_id, name=group.name, url=proposal.new_url)
        self.update_subscription(proposal.group_id)

    def refresh_subscriptions(self) -> None:
        if self._subscription_busy or (
            self.latency_runner is not None and self.latency_runner.is_busy
        ):
            self.toast("Обновление подписок или проверка задержки уже выполняется")
            return
        groups = [
            group
            for group in self.context.profiles.groups.values()
            if group.is_subscription and group.subscription_url
        ]
        if not groups:
            self.toast("Подписок нет")
            return

        updater = self._subscription_updater or self.default_subscription_updater
        targets = [(group.id, group.subscription_url) for group in groups]

        def work() -> int:
            total = 0
            for group_id, url in targets:
                try:
                    total += self._collect_outcome(group_id, url, updater(group_id, url))
                except Exception as e:
                    logger.warning("Subscription %s failed: %s", group_id, describe_update_error(e))
                    self._propose_fallback_url(group_id, url, e)
            return total

        self._subscription_busy = True
        self.toast(f"Обновляю подписки: {len(targets)}")
        self.subscriptions_thread = run_in_background(
            work,
            on_done=self._on_subscriptions_updated,
            on_error=self._on_subscriptions_failed,
            dispatch=self._loop.dispatch,
            name="tenga-subscriptions",
        )

    def _on_subscriptions_updated(self, total: int) -> None:
        self._subscription_busy = False
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist updated subscriptions: %s", e)

        self._shell.refresh_pages()
        self.toast(f"Обновлено серверов: {total}")
        self._offer_proposals()

    def _on_subscriptions_failed(self, error: BaseException) -> None:
        self._subscription_busy = False
        sent = self.context.config.sub_send_device_info
        reason = describe_update_error(error, device_info_sent=sent)
        self.toast(f"Не удалось обновить подписки: {reason}")
        self._offer_proposals()

    # --- замер задержки ---

    def set_latency_probe(self, probe: Callable[[int], int]) -> None:
        """Install the function measuring one profile's latency.

        Проба передаётся снаружи: она живёт на уровне ядра и требует запуска
        временного xray, а окно не должно знать об этом.
        """
        self._latency_probe = probe
        self.latency_runner = LatencyRunner(probe, dispatch=self._loop.dispatch)

    def _ensure_latency_runner(self) -> LatencyRunner:
        if self.latency_runner is None:
            if self._latency_probe is not None:
                self.latency_runner = LatencyRunner(
                    self._latency_probe, dispatch=self._loop.dispatch
                )
            else:
                # Весь набор меряет один временный процесс ядра.
                self.latency_runner = LatencyRunner(
                    batch_probe=make_batch_probe(self.context), dispatch=self._loop.dispatch
                )
        return self.latency_runner

    def _can_probe(self) -> bool:
        from src.db.config import ProxyMode

        state = self.context.proxy_state
        if state.is_running and state.started_mode == ProxyMode.TUN:
            self.toast(
                "Замер при активном TUN недоступен: независимый маршрут не обеспечен. Отключите TUN для проверки."
            )
            return False
        if self._subscription_busy:
            self.toast("Дождитесь обновления подписок")
            return False
        return True

    def keep_working_profiles(self, group_id: int) -> None:
        from src.ui.logic.latency import failed_profile_ids

        if not self._can_probe():
            return
        store = self.context.profiles

        def signature():
            return [(p.id, p.bean.to_share_link()) for p in store.get_profiles_in_group(group_id)]

        before = signature()
        ids = [profile_id for profile_id, _link in before]
        if not ids:
            return
        results = {}
        runner = self._ensure_latency_runner()

        def result(profile_id, value):
            results[profile_id] = value
            self._on_latency_result(profile_id, value)

        def finished():
            self._on_latency_done()
            if (
                signature() != before
                or not runner.last_run_complete
                or not self._network_available()
            ):
                self.toast("Фильтрация отменена: неполный замер, нет сети или группа изменилась")
                return
            removable = failed_profile_ids(
                ids, results, complete=True, active_id=self.context.proxy_state.started_profile_id
            )
            working = sum(value >= 0 for value in results.values())
            if not removable:
                self.toast(f"Рабочих: {working} из {len(ids)}. Серверы не удалены")
                return

            def remove():
                if signature() != before or self._subscription_busy or runner.is_busy:
                    self.toast("Группа изменилась; повторите проверку")
                    return
                for profile_id in removable:
                    if profile_id != self.context.proxy_state.started_profile_id:
                        store.remove_profile(profile_id)
                self.save_profiles()

            self._shell.confirm(
                CONFIRM_DELETE,
                "Оставить рабочие серверы?",
                f"Рабочих: {working} из {len(ids)}. Будет удалено: {len(removable)}. Активный сервер сохраняется.",
                remove,
                confirm_label="Оставить рабочие",
            )

        if not runner.run(ids, on_result=result, on_done=finished):
            self.toast("Проверка задержки уже идёт")

    def test_latency(self) -> None:
        if not self._can_probe():
            return
        profile_ids = list(self.context.profiles.profiles)
        if not profile_ids:
            self.toast("Нет серверов для проверки")
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

        by_group: dict[int, list[int]] = {}
        for profile_id in profile_ids:
            profile = self.context.profiles.get_profile(profile_id)
            if profile is not None:
                by_group.setdefault(profile.group_id, []).append(profile_id)
        self._show_ping_progress(PingProgress(by_group))
        self.toast(f"Проверяю задержку: {len(profile_ids)} серверов")

    def test_latency_for(self, profile_id: int) -> None:
        """Measure the latency of one profile."""
        if not self._can_probe():
            return
        if self.context.profiles.get_profile(profile_id) is None:
            self.toast("Сервер не найден")
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
        if not self._can_probe():
            return
        store = self.context.profiles
        if store.get_group(group_id) is None:
            self.toast("Группа не найдена")
            return

        profile_ids = [profile.id for profile in store.get_profiles_in_group(group_id)]
        if not profile_ids:
            self.toast("В группе нет серверов")
            return

        # Пинг группы — единственный случай, когда порядок строк говорит о
        # результате: список пересортировывается по задержке, пока идёт замер.
        self._shell.sort_by_ping()

        runner = self._ensure_latency_runner()
        started = runner.run(
            profile_ids,
            on_result=self._on_latency_result_live,
            on_done=self._on_latency_done,
        )
        if not started:
            self.toast("Проверка задержки уже идёт")
            return

        self._show_ping_progress(PingProgress({group_id: profile_ids}))
        self.toast(f"Проверяю задержку: {len(profile_ids)} серверов")

    def _show_ping_progress(self, progress: PingProgress | None) -> None:
        """Hand the progress of a run to the group rows; None hides it."""
        self._ping_progress = progress
        self._shell.set_ping_progress(progress)

    def _on_latency_result(self, profile_id: int, latency_ms: int) -> None:
        profile = self.context.profiles.get_profile(profile_id)
        if profile is not None:
            profile.latency_ms = latency_ms

        if self._ping_progress is None:
            return
        group_id = self._ping_progress.record(profile_id)
        if group_id is not None:
            self._shell.update_group_progress(group_id)

    def _on_latency_result_live(self, profile_id: int, latency_ms: int) -> None:
        """Store one result and schedule a re-sort of the list.

        Перерисовка склеивается по таймеру: список должен пересортировываться
        по ходу замера, но на группе в сотни профилей построчный refresh занял
        бы секунды главного цикла и превратил бы обновление в рывки.
        """
        self._on_latency_result(profile_id, latency_ms)
        self._schedule_latency_refresh()

    def _schedule_latency_refresh(self) -> None:
        if not self._shell.has_window() or self._latency_refresh_handle is not None:
            return

        def _redraw() -> bool:
            self._latency_refresh_handle = None
            self._shell.refresh_pages()
            return False

        self._latency_refresh_handle = self._loop.schedule(LATENCY_REFRESH_INTERVAL_MS, _redraw)

    def _cancel_latency_refresh(self) -> None:
        if self._latency_refresh_handle is not None:
            self._loop.cancel(self._latency_refresh_handle)
            self._latency_refresh_handle = None

    def _on_latency_done(self) -> None:
        # Итоговая перерисовка всё равно будет ниже: отложенная только
        # продублировала бы её уже после сохранения.
        self._cancel_latency_refresh()
        self._show_ping_progress(None)
        try:
            self.context.save_profiles()
        except Exception as e:
            logger.warning("Could not persist latency results: %s", e)

        self._shell.refresh_pages()
        self.toast("Проверка задержки завершена")

    # --- обновления и ссылки ---

    def set_release_fetcher(self, fetch: Callable[[], object] | None) -> None:
        """Install the function asking GitHub about core releases.

        Без неё приложение в сеть за релизами не ходит: её ставит только
        `run_app`, поэтому тесты и встраивание остаются без сетевых запросов.
        """
        self._release_fetcher = fetch

    def refresh_core_releases_if_due(self) -> None:
        """Remember the newest core releases, at most once in a few days.

        Только запоминает: о новой версии говорит страница настроек «Версия».
        """
        if not self.context.config.core_update_enabled:
            return
        fetch = self._release_fetcher
        config = self.context.config
        if fetch is None or not is_check_due(config, time.time()):
            return
        if self.core_update_thread is not None and self.core_update_thread.is_alive():
            return

        self.core_update_thread = run_in_background(
            lambda: refresh_known_releases(config, now=time.time(), fetch=fetch),
            on_done=lambda _releases: self.context.save_config(),
            # Нет сети — спросим при следующем запуске.
            on_error=lambda _error: None,
            dispatch=self._loop.dispatch,
            name="tenga-core-update",
        )

    def set_app_release_fetcher(self, fetcher) -> None:
        self._app_release_fetcher = fetcher

    def refresh_app_releases_if_due(self) -> None:
        from src.core.app_update import CHECK_INTERVAL_SECONDS, check_app_update

        context = self.context
        config = context.config
        if (
            self._app_release_fetcher is None
            or not config.app_update_enabled
            or (self.app_update_thread and self.app_update_thread.is_alive())
            or (
                config.app_update_last_attempt
                and time.time() - config.app_update_last_attempt < CHECK_INTERVAL_SECONDS
            )
        ):
            return

        def work():
            return check_app_update(
                config,
                self._app_version(),
                fetch=self._app_release_fetcher,
            )

        def done(release):
            if release and config.app_update_notified != release.version:
                self.toast(f"Доступна версия {release.version}. Откройте настройки → О программе")
                config.app_update_notified = release.version
            context.save_config()

        self.app_update_thread = run_in_background(
            work,
            on_done=done,
            on_error=lambda _error: context.save_config(),
            dispatch=self._loop.dispatch,
            name="tenga-app-update",
        )

    def import_app_link(self, raw: str) -> None:
        from src.fmt.app_links import parse_app_link

        try:
            link = parse_app_link(raw, exceptions=self.context.config.sub_source_exceptions)
        except ValueError as error:
            self.toast(str(error))
            return
        if link.operation == "unsupported":
            self.toast("VK-туннель пока не поддерживается в десктопной версии")
        elif link.operation == "subscription":
            self._shell.open_subscription_form(link.name, link.url)
        else:
            from src.ui.logic.routing_import import effective_routing, import_rows

            config, config_dir = self.context.config, self.context.config_dir
            rows = import_rows(
                effective_routing(config.routing, config_dir),
                link.routing,
                name=link.name,
                direct_default=link.direct_default,
            )
            self._shell.open_routing_import(rows, lambda: self.apply_routing_import(link.routing))
