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


@pytest.fixture(scope="session")
def _app_session(gtk_ready: None):
    """One application per test session.

    Второй экземпляр создать нельзя: GApplication экспортирует объект по
    фиксированному пути на шине сессии и не освобождает его при quit().
    Изоляция между тестами достигается сменой контекста и закрытием окна.
    """
    from src.ui.application import TengaApplication

    app = TengaApplication()
    app.register()
    yield app
    app.quit()


@pytest.fixture
def adw_app(_app_session, tmp_path):
    """The session application rebound to a throwaway config directory.

    Собственный `config_dir` обязателен: тесты меняют настройки окна, а писать
    в рабочую конфигурацию пользователя они не должны.
    """
    from src.core.context import AppContext

    _app_session.reset_for_tests(AppContext(config_dir=tmp_path))
    yield _app_session
    _app_session.reset_for_tests(None)
