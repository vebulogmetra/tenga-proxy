"""Shared pytest fixtures.

GTK-зависимые тесты помечаются маркером `gtk` и по умолчанию не запускаются
(`addopts` в pyproject.toml). Запуск: `make test-gtk`.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def gtk_ready() -> None:
    """Skip the test unless GTK4 can talk to a display."""
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk

    if not Gtk.init_check():
        pytest.skip("No display available for GTK tests")


@pytest.fixture
def adw_app(gtk_ready: None):
    """A started TengaApplication that never runs its main loop."""
    from src.ui.application import TengaApplication

    app = TengaApplication()
    app.register()
    yield app
    app.quit()
