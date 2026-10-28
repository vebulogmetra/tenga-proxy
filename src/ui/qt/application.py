"""Qt-приложение: действия, оболочка контроллера, трей, запуск.

Оркестровка — в `AppController` (src/ui/controller.py), общем с GTK. Здесь
только то, что зависит от Qt: набор действий с сочетаниями клавиш, окно,
трей, слот диалога и `_QtShell`, через который контроллер говорит с окном.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtNetwork import QNetworkInformation
from PySide6.QtWidgets import QApplication, QWidget

from src.core.config import get_asset_path
from src.ui.controller import CONFIRM_DELETE, AppController, resume_monitoring
from src.ui.logic.version import app_version, core_version
from src.ui.qt.dialogs.base import clipboard_text, open_url
from src.ui.qt.dialogs.confirm import build_confirmation
from src.ui.qt.dialogs.shortcuts import SHORTCUTS
from src.ui.qt.dispatch import QtLoop
from src.ui.qt.theme import apply_theme
from src.ui.qt.window import MainWindow

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.qt.application")

# Действия над строкой дерева: адресат — id профиля или группы, как у
# `win.*`-действий GTK-окна (src/ui/window.py).
ROW_ACTIONS = (
    "connect-profile",
    "edit-profile",
    "delete-profile",
    "profile-routing",
    "test-profile",
    "toggle-group",
    "test-group",
    "keep-working",
    "edit-group",
    "delete-group",
    "update-subscription",
    "open-subscription-page",
    "open-subscription-support",
)


def network_available() -> bool:
    """Есть ли сеть вообще; без сведений о сети считаем, что есть.

    `Local` (сеть без интернета) — тоже сеть: так же отвечает
    `Gio.NetworkMonitor` в GTK, на который опирается failover.
    """
    info = QNetworkInformation.instance()
    if info is None:
        return True
    return info.reachability() != QNetworkInformation.Reachability.Disconnected


class _QtShell:
    """`Shell` контроллера поверх `QtApplication`; без окна — ничего не делает."""

    def __init__(self, app: QtApplication) -> None:
        self._app = app

    def _window(self) -> MainWindow | None:
        return self._app.window

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self._app.last_toast_for_test = text
        window = self._window()
        if window is not None:
            window.toast(text, button=button, action=action)

    def notify(self, text: str) -> None:
        self._app.last_notification_for_test = text
        if self._app.tray_item is not None and self._app.tray is not None:
            self._app.tray_item.show_message("Veblock", text)

    def has_window(self) -> bool:
        return self._window() is not None

    def refresh_status(self) -> None:
        if (window := self._window()) is not None:
            window.refresh_status()

    def refresh_pages(self) -> None:
        if (window := self._window()) is not None:
            window.refresh_pages()
        self._app.refresh_dialog()

    def show_connecting(self, profile_name: str) -> None:
        if (window := self._window()) is not None:
            window.show_connecting(profile_name)

    def show_error(self, message: str) -> None:
        if (window := self._window()) is not None:
            window.show_error(message)

    def selected_profile_id(self) -> int | None:
        window = self._window()
        return None if window is None else window.selected_profile_id()

    def sort_by_ping(self) -> None:
        from src.ui.logic.profiles_view import SortKey

        if (window := self._window()) is not None:
            window.set_sort(SortKey.PING, ascending=True)

    def set_ping_progress(self, progress) -> None:
        if (window := self._window()) is not None:
            window.set_ping_progress(progress)

    def update_group_progress(self, group_id: int) -> None:
        if (window := self._window()) is not None:
            window.update_group_progress(group_id)

    def set_tray_state(self, state, profile_name: str) -> None:
        if self._app.tray is not None:
            self._app.tray.set_state(state, profile_name)

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        action = self._app.actions.get(name)
        if action is not None:
            action.setEnabled(enabled)
        self._app.refresh_dialog()

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None) -> None:
        # Вопрос о смене адреса приходит и при открытых настройках: тогда поверх них.
        parent = self._app.dialog_parent()
        box = build_confirmation(
            kind, heading, body, on_confirm, confirm_label=confirm_label, parent=parent
        )
        self._app.show_dialog(box, parent)

    def open_subscription_form(self, name: str, url: str) -> None:
        self._app.open_add_subscription(name=name, url=url)

    def open_routing_import(self, rows, on_confirm) -> None:
        from src.ui.qt.dialogs.routing_import import RoutingImportDialog

        parent = self._app.dialog_parent()
        self._app.show_dialog(RoutingImportDialog(rows, on_confirm, parent), parent)


class QtApplication:
    """Приложение Qt-интерфейса; `QApplication` создаётся заранее."""

    def __init__(
        self,
        context: AppContext,
        *,
        lock=None,
        lock_path=None,
        with_tray: bool = True,
        accept_activation: bool = False,
        tray_item=None,
    ) -> None:
        self.qt = QApplication.instance()
        if self.qt is None:
            raise RuntimeError("QApplication must exist before QtApplication")
        self.context = context
        self.loop = QtLoop()
        self._lock = lock
        self._lock_path = lock_path
        self._with_tray = with_tray
        self._accept_activation = accept_activation
        self._activation = None
        self._dialog = None
        self._signal_timer: QTimer | None = None
        self.window: MainWindow | None = None
        self.tray = None
        self.tray_item = tray_item
        self.last_toast_for_test = ""
        self.last_notification_for_test = ""
        self.controller = AppController(
            context,
            _QtShell(self),
            self.loop,
            network_available=network_available,
            app_version=app_version,
        )
        self.actions: dict[str, QAction] = {}
        self._handlers: dict[str, Callable[[int | None], None]] = {}
        self._register_actions()

    # --- действия ---

    def _register_actions(self) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "connect": lambda: self.controller.connect_selected(),
            "disconnect": lambda: self.controller.disconnect_proxy(),
            "toggle-connection": lambda: self.controller.toggle_connection(),
            "add-profile": self.open_add_profile,
            "add-profile-from-clipboard": self.add_profile_from_clipboard,
            "add-subscription": self.open_add_subscription,
            "add-group": self.open_add_group,
            "refresh-subscriptions": lambda: self.controller.refresh_subscriptions(),
            "test-latency": lambda: self.controller.test_latency(),
            "search": self._focus_search,
            "settings": self.open_settings,
            "about": self.open_about,
            "shortcuts": self.open_shortcuts,
            "quit": self.quit,
            "hide-window": self._hide_window,
            "activate-window": self.activate,
            "restore-routing": lambda: self.controller.restore_routing(),
        }
        for name, handler in handlers.items():
            action = QAction(name, self.qt)
            if name in SHORTCUTS:
                action.setShortcut(QKeySequence(SHORTCUTS[name]))
            action.triggered.connect(lambda _checked=False, fn=handler: fn())
            self.actions[name] = action
            self._handlers[name] = lambda _target, fn=handler: fn()

        row_handlers: dict[str, Callable[[int], None]] = {
            "connect-profile": lambda target: self.controller.connect_profile(target),
            "edit-profile": self.edit_profile,
            "delete-profile": self.delete_profile,
            "profile-routing": self.profile_routing,
            "test-profile": lambda target: self.controller.test_latency_for(target),
            "toggle-group": self._toggle_group,
            "test-group": lambda target: self.controller.test_latency_for_group(target),
            "keep-working": lambda target: self.controller.keep_working_profiles(target),
            "edit-group": self.edit_group,
            "delete-group": self.delete_group,
            "update-subscription": lambda target: self.controller.update_subscription(target),
            "open-subscription-page": lambda gid: self.open_subscription_link(
                gid, "sub_web_page_url"
            ),
            "open-subscription-support": lambda gid: self.open_subscription_link(
                gid, "sub_support_url"
            ),
        }
        # Трей и меню строк адресуют профиль или группу числом.
        for name in ROW_ACTIONS:
            self._handlers[name] = lambda target, fn=row_handlers[name]: fn(int(target))
        self.controller.sync_restore_routing()

    def activate_action(self, name: str, target=None) -> None:
        """Выполнить действие по имени; так его зовут трей и тосты."""
        handler = self._handlers.get(name)
        if handler is None:
            logger.warning("Unknown action %s", name)
            return
        handler(target)

    # --- окно и диалоги ---

    def activate(self) -> None:
        """Показать окно, создав его при первом вызове."""
        if self.window is None:
            self.window = MainWindow(self, self.context)
            self.controller.refresh_core_releases_if_due()
            self.controller.refresh_app_releases_if_due()
        self.window.present()
        resume_monitoring(self.context)

    def present_dialog(self, dialog) -> bool:
        """Один диалог за раз, как в GTK: второй не кладётся поверх первого."""
        if self._dialog is not None:
            return False
        self._dialog = dialog
        dialog.finished.connect(lambda _result, d=dialog: self._on_dialog_closed(d))
        dialog.open()
        return True

    def _on_dialog_closed(self, dialog) -> None:
        if self._dialog is dialog:
            self._dialog = None

    @property
    def current_dialog(self):
        return self._dialog

    def dialog_parent(self) -> QWidget | None:
        """Над чем открывать вопрос: над окном настроек, если оно открыто."""
        return self._dialog if self._dialog is not None else self.window

    def show_dialog(self, dialog, parent: QWidget | None = None) -> bool:
        """Показать диалог: из окна настроек — поверх него, иначе через слот.

        Формы, открытые из настроек (правка подписки, очистка журналов),
        принадлежат настройкам и слот не занимают; всё остальное — по
        одному, чтобы трей и сочетания не громоздили окна друг на друга.
        """
        if parent is not None and parent is self._dialog:
            dialog.setParent(parent, dialog.windowFlags())
            dialog.open()
            return True
        if dialog.parent() is None and self.window is not None:
            dialog.setParent(self.window, dialog.windowFlags())
        return self.present_dialog(dialog)

    def refresh_dialog(self) -> None:
        refresh = getattr(self._dialog, "refresh", None)
        if refresh is not None:
            refresh()

    # Формы. Результат уходит в контроллер теми же вызовами, что из GTK.

    def open_add_profile(self, link: str = "") -> None:
        from src.ui.qt.dialogs.profile import AddProfileDialog

        dialog = AddProfileDialog(link=link)
        dialog.profile_ready.connect(self.controller.add_profile_from_bean)
        self.show_dialog(dialog)

    def add_profile_from_clipboard(self) -> None:
        """Форма добавления со ссылкой из буфера обмена."""
        self.open_add_profile(clipboard_text())

    def open_add_subscription(
        self, *, name: str = "", url: str = "", parent: QWidget | None = None
    ) -> None:
        from src.ui.qt.dialogs.subscription import SubscriptionDialog

        dialog = SubscriptionDialog()
        dialog.name_edit.setText(name)
        dialog.url_edit.setText(url)
        dialog.subscription_ready.connect(self.controller.add_subscription)
        self.show_dialog(dialog, parent)

    def open_add_group(self) -> None:
        from src.ui.qt.dialogs.group import GroupDialog

        dialog = GroupDialog()
        dialog.group_ready.connect(self.controller.add_group)
        self.show_dialog(dialog)

    def open_settings(self) -> None:
        from src.ui.qt.dialogs.settings import SettingsDialog

        dialog = SettingsDialog(self, dispatch=self.loop.dispatch)
        # Кнопки «Сохранить» нет: правки уходят в контроллер по мере ввода.
        dialog.settings_saved.connect(self.controller.apply_settings)
        self.show_dialog(dialog)

    def open_about(self) -> None:
        from src.ui.qt.dialogs.about import AboutDialog

        core = core_version(getattr(self.context, "xray_manager", None))
        self.show_dialog(AboutDialog(app_version(), core))

    def open_shortcuts(self) -> None:
        from src.ui.qt.dialogs.shortcuts import ShortcutsDialog

        self.show_dialog(ShortcutsDialog())

    # Действия строк дерева и списка подписок.

    def _profile_or_toast(self, profile_id: int):
        profile = self.context.profiles.get_profile(profile_id)
        if profile is None:
            self.controller.toast("Профиль не найден")
        return profile

    def edit_profile(self, profile_id: int) -> None:
        from src.ui.qt.dialogs.profile import EditProfileDialog

        if (profile := self._profile_or_toast(profile_id)) is None:
            return
        dialog = EditProfileDialog(profile)
        dialog.profile_saved.connect(self.controller.save_profiles)
        self.show_dialog(dialog)

    def delete_profile(self, profile_id: int) -> None:
        if (profile := self._profile_or_toast(profile_id)) is None:
            return
        self.show_dialog(
            build_confirmation(
                CONFIRM_DELETE,
                "Удалить профиль?",
                f"«{profile.name}» будет удалён безвозвратно.",
                lambda: self.controller.delete_profile(profile_id),
                parent=self.window,
            )
        )

    def profile_routing(self, profile_id: int) -> None:
        from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog

        if (profile := self._profile_or_toast(profile_id)) is None:
            return
        dialog = ProfileRoutingDialog(profile)
        dialog.routing_saved.connect(self.controller.save_profiles)
        self.show_dialog(dialog)

    def edit_group(self, group_id: int, parent: QWidget | None = None) -> None:
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.controller.toast("Группа не найдена")
            return
        if group.is_subscription:
            from src.ui.qt.dialogs.subscription import SubscriptionDialog

            dialog = SubscriptionDialog(group)
            dialog.subscription_ready.connect(
                lambda name, url: self.controller.update_group(group_id, name=name, url=url)
            )
        else:
            from src.ui.qt.dialogs.group import GroupDialog

            dialog = GroupDialog(group)
            dialog.group_ready.connect(
                lambda name: self.controller.update_group(group_id, name=name)
            )
        self.show_dialog(dialog, parent)

    def delete_group(self, group_id: int, parent: QWidget | None = None) -> None:
        group = self.context.profiles.get_group(group_id)
        if group is None:
            self.controller.toast("Группа не найдена")
            return
        count = len(self.context.profiles.get_profiles_in_group(group_id))
        self.show_dialog(
            build_confirmation(
                CONFIRM_DELETE,
                "Удалить группу?",
                f"«{group.name}» и {count} профилей внутри будут удалены безвозвратно.",
                lambda: self.controller.delete_group(group_id),
                parent=parent or self.window,
            ),
            parent,
        )

    def open_subscription_link(self, group_id: int, field: str) -> None:
        """Ссылка провайдера; проверяется заново: файл профилей правят и вручную."""
        from src.sub.metadata import is_safe_support_url, is_safe_web_page_url

        is_safe = is_safe_web_page_url if field == "sub_web_page_url" else is_safe_support_url
        group = self.context.profiles.get_group(group_id)
        url = getattr(group, field, "") if group is not None else ""
        if not url or not is_safe(url):
            self.controller.toast("Ссылка недоступна")
            return
        open_url(url)

    def _toggle_group(self, group_id: int) -> None:
        if self.window is not None:
            self.window.toggle_group(group_id)

    def _hide_window(self) -> None:
        if self.window is not None:
            self.window.hide()

    def _focus_search(self) -> None:
        if self.window is not None:
            self.window.focus_search()

    # --- трей ---

    def start_tray(self) -> None:
        from src.ui.qt.tray import QtTrayItem
        from src.ui.tray.controller import TrayController

        if self.tray is not None:
            return
        if self.tray_item is None:
            self.tray_item = QtTrayItem()
        try:
            self.tray = TrayController(
                self, self.context, item=self.tray_item, dispatch=self.loop.dispatch
            )
            self.tray.start()
        except Exception as e:
            # Без трея приложение работает, а закрытие окна его завершает.
            logger.info("Tray is unavailable: %s", e)
            self.tray = None

    def stop_tray(self) -> None:
        if self.tray is not None:
            self.tray.stop()
            self.tray = None

    # --- жизненный цикл ---

    def start(self) -> None:
        """То, что GTK делает в `do_startup`: тема, failover, трей, активация."""
        apply_theme(getattr(self.context.config, "theme", None))
        self.controller.watch_monitor()
        if self._with_tray:
            self.start_tray()
        self._start_activation_server()

    def run(self, uris=()) -> int:
        # Процессное: тесты зовут `start()`, но не `run()`, и сигналы pytest
        # и выход общего QApplication им трогать незачем.
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.aboutToQuit.connect(self.shutdown)
        self._watch_signals()
        self.start()
        self.activate()
        for uri in uris:
            self.controller.import_app_link(uri)
        return self.qt.exec()

    def quit(self) -> None:
        self.qt.quit()

    def shutdown(self) -> None:
        if self.window is not None:
            self.window.save_geometry()
            self.window.detach()
        # Ядро гасится до снятия блокировки, как в GTK.
        self.controller.shutdown()
        self.stop_tray()
        if self._signal_timer is not None:
            self._signal_timer.stop()
        if self._activation is not None:
            self._activation.stop()
            self._activation = None
        if self._lock is not None:
            self._lock.release()

    def _watch_signals(self) -> None:
        """Ctrl+C в консоли: Python видит сигнал, только когда цикл Qt его отпускает."""
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        signal.signal(signal.SIGTERM, lambda *_: self.quit())
        self._signal_timer = QTimer()
        self._signal_timer.timeout.connect(lambda: None)
        self._signal_timer.start(250)

    def _start_activation_server(self) -> None:
        """Второй запуск на Windows передаёт ссылки первому через pipe."""
        if not self._accept_activation or self._lock is None or self._lock_path is None:
            return
        from src.sys.windows.activation import ActivationServer, pipe_address

        def deliver(uris: list[str]) -> None:
            self.loop.dispatch(self._open_uris, uris)

        try:
            self._activation = ActivationServer(pipe_address(str(self._lock_path)), deliver)
            self._activation.start()
        except OSError as e:
            logger.warning("Activation server did not start: %s", e)
            self._activation = None

    def _open_uris(self, uris: list[str]) -> None:
        self.activate()
        for uri in uris:
            self.controller.import_app_link(uri)

    # Делегаты для тестов и TrayController — те же имена, что у GTK-приложения.

    def connect_profile(self, profile_id: int) -> None:
        self.controller.connect_profile(profile_id)

    def set_connection_service(self, service) -> None:
        self.controller.set_connection_service(service)

    def set_release_fetcher(self, fetch) -> None:
        self.controller.set_release_fetcher(fetch)

    def set_app_release_fetcher(self, fetcher) -> None:
        self.controller.set_app_release_fetcher(fetcher)


def run_app(
    config_dir=None,
    lock=None,
    with_tray: bool = True,
    uris=(),
    lock_path=None,
    accept_activation: bool = False,
) -> int:
    """Точка входа Qt-интерфейса; сигнатура как у GTK-шного `run_app`."""
    from src.core.app_update import fetch_app_releases
    from src.core.context import init_context
    from src.core.core_update import fetch_releases
    from src.core.monitor import attach_monitor
    from src.sub.route import local_proxy_url

    qt = QApplication.instance() or QApplication(["tenga-proxy"])
    qt.setApplicationName("Veblock")
    qt.setDesktopFileName("tenga-proxy")
    qt.setWindowIcon(QIcon(str(get_asset_path("tenga-proxy.ico"))))
    QNetworkInformation.loadDefaultBackend()

    context = init_context(config_dir=config_dir)
    app = QtApplication(
        context,
        lock=lock,
        lock_path=lock_path,
        with_tray=with_tray,
        accept_activation=accept_activation,
    )
    # Монитор на цикле Qt: таймеры и доставка результатов проверок.
    attach_monitor(context, loop=app.loop)
    app.set_release_fetcher(fetch_releases)
    app.set_app_release_fetcher(
        lambda: fetch_app_releases(lambda: local_proxy_url(context.config, context.proxy_state))
    )
    return app.run(uris)
