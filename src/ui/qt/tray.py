"""Элемент трея на `QSystemTrayIcon` с интерфейсом `StatusNotifierItem`.

`TrayController` (src/ui/tray/controller.py) не знает, кто под ним: SNI на
Linux, Win32 или этот элемент. Меню строится из той же модели
`build_menu()`; сигналы Qt приходят в главном потоке, поэтому обработчики
вызываются напрямую, без `dispatch`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from src.ui.qt.icons import flagged
from src.ui.tray.dbusmenu import MenuItem

logger = logging.getLogger("tenga.ui.qt.tray")


def icon_file(icon_name: str, theme_path: str) -> Path:
    """`.ico` из `win/`, если есть, иначе svg: Qt читает оба формата везде."""
    base = Path(theme_path)
    ico = base / "win" / f"{icon_name}.ico"
    return ico if ico.is_file() else base / f"{icon_name}.svg"


class QtTrayItem:
    def __init__(
        self,
        *,
        available: Callable[[], bool] = QSystemTrayIcon.isSystemTrayAvailable,
    ) -> None:
        self._available = available
        self._icon = QSystemTrayIcon()
        self._menu = QMenu()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None

    def publish(self) -> None:
        if not self._available():
            # TrayController поймает ошибку и оставит приложение без трея:
            # тогда закрытие окна завершает программу, а не прячет её.
            raise RuntimeError("Системный трей недоступен")
        self._icon.show()

    def shutdown(self) -> None:
        self._icon.hide()

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        self._icon.setIcon(QIcon(str(icon_file(icon_name, theme_path))))

    def set_status(self, status: str) -> None:
        """Статусы — понятие StatusNotifierItem; у QSystemTrayIcon их нет."""

    def set_tooltip(self, text: str) -> None:
        self._icon.setToolTip(text)

    def set_menu(self, items: list[MenuItem]) -> None:
        self._menu.clear()
        self._fill(self._menu, items)

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        self._on_primary = handler

    def show_message(self, title: str, text: str) -> None:
        """Системное уведомление: на Windows 10 и 11 — тост."""
        self._icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information)

    @property
    def menu(self) -> QMenu:
        return self._menu

    def _fill(self, menu: QMenu, items: list[MenuItem]) -> None:
        for item in items:
            if not item.visible:
                continue
            if item.is_separator:
                menu.addSeparator()
                continue
            icon, label = flagged(item.label)
            if item.children:
                submenu = menu.addMenu(label)
                if icon is not None:
                    submenu.setIcon(icon)
                submenu.setEnabled(item.enabled)
                self._fill(submenu, item.children)
                continue
            action = menu.addAction(label)
            if icon is not None:
                action.setIcon(icon)
            action.setEnabled(item.enabled)
            if item.checked is not None:
                action.setCheckable(True)
                action.setChecked(item.checked)
            if item.action:
                action.triggered.connect(
                    lambda _checked=False, name=item.action, target=item.target: self._activate(
                        name, target
                    )
                )

    def _activate(self, name: str, target: int | None) -> None:
        if self._on_activate is not None:
            self._on_activate(name, target)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger and self._on_primary is not None:
            self._on_primary()
