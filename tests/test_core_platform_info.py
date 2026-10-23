"""Признак платформы и флаги запуска дочерних процессов."""

from __future__ import annotations

from src.core import platform_info


def test_no_window_is_empty_outside_windows(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert platform_info.no_window() == {}


def test_no_window_hides_console_on_windows(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert platform_info.no_window() == {"creationflags": 0x08000000}
