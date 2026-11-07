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


# Цвета состояний общие для GTK и Qt. Всё остальное — системная палитра.
ACCENT = "#36c9b5"
ERROR_TEXT = "#d13438"

STATE_COLORS = {
    "status-connected": ACCENT,
    "status-connecting": "#ffa64d",
    "status-disconnecting": "#ffa64d",
    "status-error": "#e07078",
    "status-blocked": "#e07078",
    "status-disconnected": "#8a969d",
    "status-empty": "#8a969d",
}

# Свечение под логотипом: его нет при отключении и пустом хранилище.
GLOW_COLORS = {
    "status-connected": "#5ed3c7",
    "status-connecting": "#ffa64d",
    "status-disconnecting": "#ffa64d",
    "status-error": "#e07078",
    "status-blocked": "#e07078",
}

PANEL_MIN_WIDTH = 280
PANEL_MAX_WIDTH = 360
LOGO_SIZE = 240
LOGO_SIZE_COMPACT = 140
# Ниже этой высоты окна панель переходит в компактный режим.
COMPACT_HEIGHT = 680


def glow_color(css_class: str) -> str | None:
    """Colour of the halo under the logo, or None when there is no halo."""
    return GLOW_COLORS.get(css_class)
