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
from typing import TYPE_CHECKING, Any, Protocol

from src.core.core_update import is_check_due, refresh_known_releases
from src.core.failover import FailoverController
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.latency import LatencyRunner, PingProgress, make_batch_probe
from src.ui.logic.status import ConnectionState
from src.ui.logic.subscriptions_view import describe_update_error, describe_url_change
from src.ui.logic.version import app_version

if TYPE_CHECKING:
    from src.core.context import AppContext
    from src.core.main_loop import MainLoop

logger = logging.getLogger("tenga.ui.controller")

# Шаг склейки перерисовок на время замера задержки.
LATENCY_REFRESH_INTERVAL_MS = 150

# Виды подтверждений: оболочка выбирает по ним кнопки и их внешний вид.
CONFIRM_DELETE = "delete"
CONFIRM_URL_CHANGE = "url-change"


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

    def open_routing_import(self, rows: list, on_confirm: Callable[[], None]) -> None: ...


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
        self._profile_activation_handler: Callable[[int], None] | None = None
        self._connection_service = None
        self.connection_thread = None
        self._failover: FailoverController | None = None
        self._release_fetcher: Callable[[], object] | None = None
        self.core_update_thread = None
        self.app_update_thread = None
        self._app_release_fetcher = None

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
        if self._connection_service is not None:
            self._connection_service.shutdown(self.connection_thread)

    # --- данные ---

    def add_profile_from_bean(self, bean, group_id: int | None = None):
        """Store a parsed profile and persist it."""
        entry = self.context.profiles.add_profile(bean, group_id=group_id)
        self._save_profiles()
        self._shell.refresh_pages()
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
        self._shell.refresh_pages()
        self.toast(f"Профиль удалён: {name}")

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
        if url is not None:
            group.subscription_url = url
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
                raise OSError("Запись профилей не выполнена")
        except Exception as e:
            logger.warning("Could not persist profiles: %s", e)
            self.toast("Не удалось сохранить профили")

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

    # --- подключение (задача 4) ---

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
            self.toast("Профиль не найден")
            return

        if self.connection_busy():
            # Два одновременных запуска оставили бы висящий процесс xray.
            self.toast("Подключение уже выполняется")
            return

        self._shell.show_connecting(profile.name)
        # Промежуточное состояние живёт только в UI: в proxy_state его нет,
        # и сам по себе трей о нём не узнает.
        self._shell.set_tray_state(ConnectionState.CONNECTING, profile.name)

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
            self.toast("Выберите профиль в списке")
            return
        self.connect_profile(profile_id)

    def toggle_connection(self) -> None:
        if self.context.proxy_state.is_running:
            self.disconnect_proxy()
            return
        self.connect_selected()

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
        else:
            self.toast(f"Не удалось подключиться: {result.error}")
            self._shell.show_error(result.error)
            self._shell.set_tray_state(ConnectionState.ERROR, "")

        self._refresh_window()

    def _on_disconnection_done(self, result) -> None:
        if result.ok:
            self.toast("Отключено")
        else:
            self.toast(f"Не удалось отключиться: {result.error}")
        self._refresh_window()

    def _on_connection_failed(self, error: BaseException) -> None:
        self.toast(f"Ошибка подключения: {error}")
        self._shell.show_error(str(error))
        self._shell.set_tray_state(ConnectionState.ERROR, "")
        self._refresh_window()

    def _refresh_window(self) -> None:
        self._shell.refresh_status()
        self._shell.refresh_pages()

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

    # --- подписки (задача 5) ---

    # --- замер задержки (задача 6) ---

    # --- обновления и ссылки (задача 7) ---
