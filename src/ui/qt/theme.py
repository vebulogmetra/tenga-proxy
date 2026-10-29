"""Цветовая схема Qt-интерфейса по настройке «Тема»."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from src.ui.logic.appearance import normalize_theme

if TYPE_CHECKING:
    from src.core.context import AppContext


def initialize_default_theme(context: AppContext) -> None:
    """Светлая тема нового Qt-профиля; сохранённый выбор не переопределяется."""
    if context.config.theme != "system":
        return
    try:
        saved = json.loads((context.config_dir / "settings.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = {}
    except (OSError, ValueError):
        return
    if isinstance(saved, dict) and "theme" not in saved:
        context.config.theme = "light"


def apply_theme(theme: str | None) -> None:
    """Светлая или тёмная схема; в «Системной» Qt сам следит за ОС."""
    scheme = {
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }.get(normalize_theme(theme), Qt.ColorScheme.Unknown)
    QGuiApplication.styleHints().setColorScheme(scheme)
