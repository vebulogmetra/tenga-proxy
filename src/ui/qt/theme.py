"""Цветовая схема Qt-интерфейса по настройке «Тема»."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from src.ui.logic.appearance import normalize_theme


def apply_theme(theme: str | None) -> None:
    """Светлая или тёмная схема; в «Системной» Qt сам следит за ОС."""
    scheme = {
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }.get(normalize_theme(theme), Qt.ColorScheme.Unknown)
    QGuiApplication.styleHints().setColorScheme(scheme)
