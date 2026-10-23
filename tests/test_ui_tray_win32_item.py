"""Элемент трея Win32: логика поверх подменённого окна сообщений."""

from __future__ import annotations

import pytest

from src.ui.tray.dbusmenu import MenuItem
from src.ui.tray.win32.item import Win32TrayItem


class FakeBackend:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.updates = []
        self.chosen = 0
        self.shown_ops = None
        self.on_event = None

    def start(self, on_event):
        self.started = True
        self.on_event = on_event

    def update(self, icon_path, tooltip):
        self.updates.append((icon_path, tooltip))

    def show_menu(self, ops):
        self.shown_ops = ops
        return self.chosen

    def stop(self):
        self.stopped = True


def immediate(fn, *args):
    fn(*args)


@pytest.fixture
def item(tmp_path):
    backend = FakeBackend()
    tray = Win32TrayItem(backend=backend, dispatch=immediate, icons_dir=tmp_path)
    return tray, backend


def test_publish_starts_backend(item):
    tray, backend = item

    tray.publish()

    assert backend.started


def test_icon_name_maps_to_ico_file(item, tmp_path):
    tray, backend = item
    tray.publish()

    tray.set_icon("tenga-proxy-connected", "/ignored/theme/path")

    assert backend.updates[-1][0] == str(tmp_path / "tenga-proxy-connected.ico")


def test_tooltip_is_cut_to_127_chars(item):
    tray, backend = item
    tray.publish()

    tray.set_tooltip("x" * 300)

    assert len(backend.updates[-1][1]) == 127


def test_left_click_runs_primary(item):
    tray, backend = item
    calls = []
    tray.set_on_primary(lambda: calls.append("primary"))
    tray.publish()

    backend.on_event("primary")

    assert calls == ["primary"]


def test_menu_choice_runs_action_with_target(item):
    tray, backend = item
    got = []
    tray.set_on_activate(lambda action, target: got.append((action, target)))
    tray.set_menu([MenuItem("A", action="app.connect-profile", target=5)])
    tray.publish()
    backend.chosen = 1

    backend.on_event("menu")

    assert got == [("app.connect-profile", 5)]


def test_dismissed_menu_does_nothing(item):
    tray, backend = item
    got = []
    tray.set_on_activate(lambda *a: got.append(a))
    tray.set_menu([MenuItem("A", action="app.connect")])
    tray.publish()
    backend.chosen = 0

    backend.on_event("menu")

    assert got == []


def test_shutdown_stops_backend_once(item):
    tray, backend = item
    tray.publish()

    tray.shutdown()
    tray.shutdown()

    assert backend.stopped


@pytest.mark.windows
def test_real_window_starts_and_stops(tmp_path):
    from src.ui.tray.win32.backend import NotifyIconWindow

    window = NotifyIconWindow()
    window.start(lambda _kind: None)
    window.update("", "Tenga Proxy test")
    window.stop()
