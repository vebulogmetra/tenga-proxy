"""Подписка на POSIX-сигналы: на Windows её нет. Дисплей не нужен."""

from __future__ import annotations

import pytest


def test_signal_handlers_are_skipped_on_windows(monkeypatch):
    pytest.importorskip("gi")
    from src.core import platform_info
    from src.ui import application

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    calls = []
    monkeypatch.setattr(application.GLib, "unix_signal_add", lambda *a: calls.append(a) or 1)
    app = application.TengaApplication.__new__(application.TengaApplication)

    application.TengaApplication._setup_signal_handlers(app)

    assert calls == []
    assert app._signal_source_ids == []
