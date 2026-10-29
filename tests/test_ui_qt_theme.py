"""Светлая тема по умолчанию только у Qt, с сохранением явного выбора."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from src.core.context import AppContext
from src.ui.qt.theme import initialize_default_theme

pytestmark = pytest.mark.qt


def test_fresh_qt_settings_default_to_light(tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config.theme == "system"
    initialize_default_theme(context)
    assert context.config.theme == "light"
    assert not (tmp_path / "settings.json").exists()


@pytest.mark.parametrize("theme", ["dark", "light", "system"])
def test_saved_theme_is_preserved(tmp_path, theme):
    (tmp_path / "settings.json").write_text(json.dumps({"theme": theme}), encoding="utf-8")
    context = AppContext(config_dir=tmp_path)
    initialize_default_theme(context)
    assert context.config.theme == theme


def test_old_settings_without_theme_default_to_light(tmp_path):
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    context = AppContext(config_dir=tmp_path)
    initialize_default_theme(context)
    assert context.config.theme == "light"
