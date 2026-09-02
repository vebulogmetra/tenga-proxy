from __future__ import annotations

import signal
from types import SimpleNamespace

from src.ui import app as app_module


def test_signal_handlers_registered_via_glib(monkeypatch):
    registered: list[tuple[int, int]] = []

    def fake_unix_signal_add(priority, signum, callback, *args):
        registered.append((priority, signum))
        return 42

    monkeypatch.setattr(app_module.GLib, "unix_signal_add", fake_unix_signal_add)

    def _fail(*_args):
        raise AssertionError("signal.signal used")

    monkeypatch.setattr(app_module.signal, "signal", _fail)

    app = app_module.TengaApp.__new__(app_module.TengaApp)
    app._signal_source_ids = []
    app._setup_signal_handlers()

    assert sorted(s for _, s in registered) == sorted([signal.SIGINT, signal.SIGTERM])
    assert app._signal_source_ids == [42, 42]


def test_on_signal_quits_and_returns_source_remove():
    calls: list[str] = []
    app = app_module.TengaApp.__new__(app_module.TengaApp)
    app._lock = SimpleNamespace(release=lambda: calls.append("release"))
    app.quit = lambda: calls.append("quit")

    assert app._on_signal(signal.SIGTERM) is app_module.GLib.SOURCE_REMOVE
    assert calls == ["release", "quit"]
