from __future__ import annotations

from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme


def test_every_theme_has_a_label():
    assert THEMES == ["system", "light", "dark"]
    assert set(THEME_LABELS) == set(THEMES)


def test_known_themes_are_kept():
    for theme in THEMES:
        assert normalize_theme(theme) == theme


def test_an_unknown_value_follows_the_system():
    # «0» — значение по умолчанию из прежних версий настроек.
    assert normalize_theme("0") == "system"
    assert normalize_theme("") == "system"
    assert normalize_theme(None) == "system"


# --- цвета состояний и размеры ------------------------------------------------


def test_state_colors_match_the_qt_palette():
    from src.ui.logic.appearance import ACCENT, GLOW_COLORS, STATE_COLORS, glow_color

    assert ACCENT == "#36c9b5"
    assert STATE_COLORS["status-connected"] == "#36c9b5"
    assert STATE_COLORS["status-connecting"] == "#ffa64d"
    assert STATE_COLORS["status-error"] == STATE_COLORS["status-blocked"] == "#e07078"
    assert STATE_COLORS["status-disconnected"] == "#8a969d"
    # Свечение: бирюзовое у подключения, оранжевое у операции, красное у ошибки,
    # нет — у отключения и пустого хранилища.
    assert GLOW_COLORS["status-connected"] == "#5ed3c7"
    assert glow_color("status-connecting") == "#ffa64d"
    assert glow_color("status-disconnected") is None
    assert glow_color("status-empty") is None
    assert glow_color("unknown-class") is None


def test_panel_sizes_are_shared():
    from src.ui.logic.appearance import (
        COMPACT_HEIGHT,
        LOGO_SIZE,
        LOGO_SIZE_COMPACT,
        PANEL_MAX_WIDTH,
        PANEL_MIN_WIDTH,
    )

    assert (PANEL_MIN_WIDTH, PANEL_MAX_WIDTH) == (280, 360)
    assert LOGO_SIZE > LOGO_SIZE_COMPACT > 0
    assert COMPACT_HEIGHT == 680
