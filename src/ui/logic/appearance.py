"""Colour scheme choice of the application (GTK-free)."""

from __future__ import annotations

THEMES = ["system", "light", "dark"]

THEME_LABELS = {
    "system": "Как в системе",
    "light": "Светлая",
    "dark": "Тёмная",
}

DEFAULT_THEME = "system"


def normalize_theme(value: str | None) -> str:
    """Return a known theme key; anything else follows the system.

    В старых настройках поле `theme` хранило «0» — его, как и любое
    незнакомое значение, понимаем как системную тему.
    """
    return value if value in THEMES else DEFAULT_THEME
