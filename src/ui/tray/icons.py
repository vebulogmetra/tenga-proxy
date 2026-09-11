"""Tray icon names and where their files live.

Иконки лежат в собственном каталоге, а не в системной теме: приложение ставится
как AppImage, и в теме пользователя его имён нет. Каталог отдаётся панели через
свойство `IconThemePath`.

Цвет в этих файлах задан явно, а не через `currentColor`. Панель при заданном
`IconThemePath` подхватывает файл как картинку (`Gio.FileIcon`) и symbolic-
перекраску под цвет своей темы не делает, поэтому `currentColor` разрешался бы
в чёрный по умолчанию SVG и иконка пропадала бы на тёмной панели. Фигура
белая, с полупрозрачной тёмной каймой: читается и на тёмной панели GNOME, и на
светлых панелях KDE или XFCE.

Комментариев XML в самих файлах нет намеренно: загрузчик gdk-pixbuf определяет
формат по началу файла и на комментарии перед тегом `<svg>` отказывается
распознавать SVG.
"""

from __future__ import annotations

from pathlib import Path

from src.core.config import BUNDLE_DIR
from src.ui.logic.status import ConnectionState

ICON_DISCONNECTED = "tenga-proxy-disconnected"
ICON_CONNECTING = "tenga-proxy-connecting"
ICON_CONNECTED = "tenga-proxy-connected"

ICON_NAMES = (ICON_DISCONNECTED, ICON_CONNECTING, ICON_CONNECTED)

_BY_STATE = {
    ConnectionState.DISCONNECTED: ICON_DISCONNECTED,
    ConnectionState.CONNECTING: ICON_CONNECTING,
    ConnectionState.CONNECTED: ICON_CONNECTED,
    # У ошибки своей иконки нет: состояние «не подключено», а причина видна
    # в подсказке и в окне.
    ConnectionState.ERROR: ICON_DISCONNECTED,
}


def icons_directory() -> Path:
    """Directory holding the tray icons."""
    return BUNDLE_DIR / "assets" / "icons"


def icon_name_for(state: ConnectionState) -> str:
    """Icon name for one connection state."""
    return _BY_STATE.get(state, ICON_DISCONNECTED)
