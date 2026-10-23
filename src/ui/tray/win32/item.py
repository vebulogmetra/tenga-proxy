"""Элемент трея Windows с тем же интерфейсом, что у `StatusNotifierItem`.

Окно сообщений и вызовы Shell_NotifyIcon живут в `backend.py` и своём потоке;
здесь — только состояние и решения: какой файл иконки, какой пункт выбран.
События окна приходят из его потока, поэтому обработчики приложения
вызываются через `dispatch` (по умолчанию `GLib.idle_add`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from src.ui.tray.dbusmenu import MenuItem, MenuModel
from src.ui.tray.win32.menu_ops import menu_ops

logger = logging.getLogger("tenga.ui.tray.win32")

# szTip в NOTIFYICONDATAW — 128 символов с завершающим нулём.
TOOLTIP_LIMIT = 127


def _glib_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


def default_icons_dir() -> Path:
    from src.core.config import BUNDLE_DIR

    return BUNDLE_DIR / "assets" / "icons" / "win"


class Win32TrayItem:
    def __init__(self, *, backend=None, dispatch=_glib_dispatch, icons_dir: Path | None = None):
        if backend is None:
            from src.ui.tray.win32.backend import NotifyIconWindow

            backend = NotifyIconWindow()
        self._backend = backend
        self._dispatch = dispatch
        self._icons_dir = icons_dir or default_icons_dir()
        self._icon_path = ""
        self._tooltip = ""
        self._menu = MenuModel([])
        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None
        self._published = False

    def publish(self) -> None:
        self._backend.start(self._on_event)
        self._published = True
        self._push()

    def shutdown(self) -> None:
        if not self._published:
            return
        self._published = False
        self._backend.stop()

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        # theme_path нужен панелям Linux; на Windows иконка — файл .ico.
        self._icon_path = str(self._icons_dir / f"{icon_name}.ico")
        self._push()

    def set_status(self, status: str) -> None:
        """Statuses are a StatusNotifierItem notion; Windows has none."""

    def set_tooltip(self, text: str) -> None:
        self._tooltip = text[:TOOLTIP_LIMIT]
        self._push()

    def set_menu(self, items: list[MenuItem]) -> None:
        self._menu = MenuModel(items)

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        self._on_primary = handler

    def _push(self) -> None:
        if self._published:
            self._backend.update(self._icon_path, self._tooltip)

    def _on_event(self, kind: str) -> None:
        """Вызывается из потока окна."""
        if kind == "primary" and self._on_primary is not None:
            self._dispatch(self._on_primary)
        elif kind == "menu":
            chosen = self._backend.show_menu(menu_ops(self._menu))
            item = self._menu.find(chosen) if chosen else None
            if item is not None and item.action and self._on_activate is not None:
                self._dispatch(self._on_activate, item.action, item.target)
