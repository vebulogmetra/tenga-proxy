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


@pytest.fixture
def private_bus():
    """A throwaway session bus for the tray tests.

    Свой экземпляр шины на тест: элемент трея занимает уникальное имя и
    регистрируется у watcher, а делать это на живой шине пользователя нельзя —
    там работает установленное приложение.
    """
    pytest.importorskip("gi")
    from gi.repository import Gio

    bus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
    bus.up()
    try:
        yield bus.get_bus_address()
    finally:
        bus.down()


@pytest.fixture
def bus_connection(private_bus):
    """A client connection to the private bus."""
    from gi.repository import Gio

    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    return Gio.DBusConnection.new_for_address_sync(private_bus, flags, None, None)


@pytest.fixture
def dbus_call():
    """Call a D-Bus method while still driving the main loop.

    `call_sync` здесь непригоден: объект обслуживается главным циклом того же
    потока, и синхронный вызов блокирует его до таймаута. Поэтому вызов
    асинхронный, а цикл крутится вручную до готовности ответа.
    """
    from gi.repository import Gio, GLib

    def call(connection, name, path, interface, method, params=None, timeout=5.0):
        box: dict = {}

        def done(source, result):
            try:
                box["value"] = source.call_finish(result)
            except Exception as e:  # noqa: BLE001 - ошибка возвращается вызывающему
                box["error"] = e

        connection.call(
            name, path, interface, method, params, None, Gio.DBusCallFlags.NONE, 2000, None, done
        )

        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + int(timeout * 1_000_000)
        while not box and GLib.get_monotonic_time() < deadline:
            context.iteration(True)

        if "error" in box:
            raise box["error"]
        if "value" not in box:
            raise TimeoutError(f"{interface}.{method} did not answer in {timeout}s")
        return box["value"]

    return call


@pytest.fixture
def pump():
    """Drive the main loop for a short while."""
    from gi.repository import GLib

    def run(seconds: float = 0.2) -> None:
        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + int(seconds * 1_000_000)
        while GLib.get_monotonic_time() < deadline:
            context.iteration(False)

    return run
