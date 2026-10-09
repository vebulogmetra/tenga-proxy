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
