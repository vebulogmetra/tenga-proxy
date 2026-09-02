"""Connect the tray item to the application state.

Иконка, подсказка и меню — производные от состояния прокси; действия меню
переадресуются существующим `Gio.Action` приложения, чтобы поведение трея и
окна не разъезжалось.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.ui.logic.status import ConnectionState
from src.ui.tray4.icons import icon_name_for, icons_directory
from src.ui.tray4.menu import build_menu

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.tray")


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


class TrayController:
    """Keeps the tray item in step with the proxy state."""

    def __init__(
        self,
        application,
        context: AppContext,
        *,
        item=None,
        dispatch: Callable[..., object] = _default_dispatch,
    ) -> None:
        self._app = application
        self._context = context
        self._dispatch = dispatch
        self._state = ConnectionState.DISCONNECTED
        self._profile_name = ""
        self._running = False

        if item is None:
            from src.ui.tray4.sni import StatusNotifierItem

            item = StatusNotifierItem()
        self._item = item

    def start(self) -> None:
        """Publish the item and start following the proxy state."""
        self._item.set_on_activate(self._on_menu_action)
        self._item.set_on_primary(lambda: self._activate("activate-window"))
        self._item.publish()
        self._context.proxy_state.add_listener(self._on_proxy_state)
        self._running = True
        self.refresh()

    def stop(self) -> None:
        """Remove the item and stop following the state."""
        if not self._running:
            return
        self._running = False
        try:
            self._context.proxy_state.remove_listener(self._on_proxy_state)
        except Exception:
            logger.debug("Tray listener was already gone", exc_info=True)
        self._item.shutdown()

    def set_state(self, state: ConnectionState, profile_name: str = "") -> None:
        """Change what the tray shows."""
        self._state = state
        self._profile_name = profile_name
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the icon, the tooltip and the menu."""
        self._item.set_icon(icon_name_for(self._state), str(icons_directory()))
        self._item.set_tooltip(self._tooltip())
        self._item.set_menu(
            build_menu(
                self._state,
                self._profiles(),
                profile_name=self._profile_name,
                active_profile_id=self._active_profile_id(),
            )
        )

    def _tooltip(self) -> str:
        if self._state is ConnectionState.CONNECTED:
            return f"Tenga Proxy: {self._profile_name or 'подключено'}"
        if self._state is ConnectionState.CONNECTING:
            return "Tenga Proxy: подключение…"
        if self._state is ConnectionState.ERROR:
            return "Tenga Proxy: ошибка"
        return "Tenga Proxy: отключено"

    def _profiles(self) -> list:
        return list(self._context.profiles.profiles.values())

    def _active_profile_id(self) -> int | None:
        state = self._context.proxy_state
        if not state.is_running or state.started_profile_id < 0:
            return None
        return state.started_profile_id

    def _on_proxy_state(self, state) -> None:
        # Состояние меняет поток подключения, а работа с D-Bus должна идти из
        # главного цикла.
        self._dispatch(self._apply_proxy_state, state.is_running, state.started_profile_id)

    def _apply_proxy_state(self, is_running: bool, profile_id: int) -> None:
        if is_running:
            profile = self._context.profiles.get_profile(profile_id)
            self.set_state(ConnectionState.CONNECTED, profile.name if profile else "")
        else:
            self.set_state(ConnectionState.DISCONNECTED, "")

    def _on_menu_action(self, action: str, target: int | None) -> None:
        self._activate(action.removeprefix("app."), target)

    def _activate(self, name: str, target: int | None = None) -> None:
        try:
            self._app.activate_action(name, target)
        except Exception as e:
            # Клик из трея не должен ронять процесс: приложение продолжает
            # работать, даже если действие не нашлось.
            logger.warning("Tray action %s failed: %s", name, e)
