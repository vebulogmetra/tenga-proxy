"""Отличия компоновки по ОС: без GTK, обе ветки на любой ОС."""

from __future__ import annotations

import pytest

from src.core import platform_info
from src.ui.logic import platform_layout

FLAGS = [
    platform_layout.adaptive_dialog_width,
    platform_layout.wrapping_action_buttons,
    platform_layout.compact_subscription_rows,
    platform_layout.toasts_above_navigation,
    platform_layout.bundled_flag_images,
    platform_layout.monitoring_on_general_settings_page,
    platform_layout.monolith_status_logo,
]


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("flag", FLAGS, ids=lambda f: f.__name__)
def test_layout_differences_follow_the_platform(monkeypatch, flag, windows):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)

    assert flag() is windows


@pytest.mark.parametrize(
    ("windows", "expected"),
    [(False, ["style.css"]), (True, ["style.css", "style-windows.css"])],
)
def test_windows_stylesheet_goes_over_the_common_one(monkeypatch, windows, expected):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)

    assert platform_layout.stylesheets() == expected
