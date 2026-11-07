"""Цвета состояний одни в GTK и Qt: оба берут их из `appearance.py`."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ui.logic.appearance import ACCENT, STATE_COLORS


def test_qss_uses_the_shared_state_colors():
    qss = Path("src/ui/qt/style.qss").read_text(encoding="utf-8")
    assert ACCENT in qss
    for css_class in ("status-connected", "status-connecting", "status-error"):
        assert STATE_COLORS[css_class] in qss


def test_qt_monolith_glow_comes_from_appearance():
    pytest.importorskip("PySide6")
    import inspect

    from src.ui.qt.widgets import status_card

    source = inspect.getsource(status_card)
    assert "GLOW_COLORS" in source or "glow_color" in source
    assert "#ffa64d" not in source


def test_gtk_css_uses_the_shared_state_colors():
    css = Path("src/ui/style.css").read_text(encoding="utf-8")
    assert ACCENT in css
    for css_class in ("status-connecting", "status-error", "status-disconnected"):
        assert STATE_COLORS[css_class] in css
