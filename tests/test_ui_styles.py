"""Platform stylesheet loading and GTK CSS syntax."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


@pytest.mark.parametrize("windows", [False, True])
def test_platform_stylesheets(monkeypatch, windows):
    from src.ui import window

    loaded = []
    monkeypatch.setattr(window.platform_info, "IS_WINDOWS", windows)
    monkeypatch.setattr(window.Gdk.Display, "get_default", lambda: object())
    monkeypatch.setattr(
        window.Gtk.StyleContext,
        "add_provider_for_display",
        lambda _display, provider, _priority: loaded.append(provider),
    )
    window.load_css()

    assert len(loaded) == (2 if windows else 1)
    # Проверяем содержимое реально загруженного провайдера, а не только имя файла.
    assert b"Segoe UI" not in loaded[0].to_string().encode()
    if windows:
        assert "Segoe UI" in loaded[1].to_string()


def test_stylesheets_parse_without_errors():
    from gi.repository import Gtk

    from src.ui import window

    errors = []
    for name in ("style.css", "style-windows.css"):
        provider = Gtk.CssProvider()
        provider.connect(
            "parsing-error", lambda _provider, _section, error: errors.append(str(error))
        )
        provider.load_from_path(str(Path(window.__file__).with_name(name)))
    assert errors == []


def test_windows_name_label_resets_flag_on_reuse(gtk_ready):
    from src.ui.widgets.name_label import FlagNameLabel

    label = FlagNameLabel()
    label.set_text("🇷🇺Москва")
    assert label.get_text() == "🇷🇺Москва"
    assert label._label.get_text() == "Москва"
    assert label._flag.get_visible()
    assert label._flag.get_storage_type().value_nick != "empty"

    label.set_text("Без флага")
    assert label._label.get_text() == "Без флага"
    assert not label._flag.get_visible()

    label.set_text("🇿🇿Неизвестно")
    assert label._label.get_text() == "🇿🇿Неизвестно"
    assert not label._flag.get_visible()


@pytest.mark.parametrize("windows", [False, True])
def test_name_label_is_platform_specific(gtk_ready, monkeypatch, windows):
    from gi.repository import Gtk

    from src.core import platform_info
    from src.ui.widgets.name_label import FlagNameLabel, name_label

    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
    assert isinstance(name_label(), FlagNameLabel if windows else Gtk.Label)


@pytest.mark.parametrize("windows", [False, True])
def test_toasts_leave_windows_navigation_outside_overlay(gtk_ready, monkeypatch, windows):
    from types import SimpleNamespace

    from gi.repository import Adw

    from src.core.context import ProxyState
    from src.ui import window

    Adw.init()
    monkeypatch.setattr(window.platform_info, "IS_WINDOWS", windows)
    monkeypatch.setattr(window.MainWindow, "refresh_status", lambda _self: None)
    monkeypatch.setattr(window.MainWindow, "refresh_pages", lambda _self: None)
    context = SimpleNamespace(config=SimpleNamespace(window_size=""), proxy_state=ProxyState())
    main = window.MainWindow(application=None, context=context)
    try:
        ancestors = []
        parent = main.view_switcher_bar.get_parent()
        while parent is not None:
            ancestors.append(parent)
            parent = parent.get_parent()
        assert (main.toast_overlay in ancestors) is not windows
    finally:
        main.destroy()
