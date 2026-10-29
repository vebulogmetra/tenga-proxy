"""Stylesheet loading, GTK CSS syntax and the layout it relies on."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


def test_stylesheet_is_loaded(monkeypatch):
    from src.ui import window

    loaded = []
    monkeypatch.setattr(window.Gdk.Display, "get_default", lambda: object())
    monkeypatch.setattr(
        window.Gtk.StyleContext,
        "add_provider_for_display",
        lambda _display, provider, _priority: loaded.append(provider),
    )
    window.load_css()

    assert len(loaded) == 1
    # Проверяем содержимое реально загруженного провайдера, а не только имя файла.
    assert b"Segoe UI" not in loaded[0].to_string().encode()


def test_stylesheet_parses_without_errors():
    from gi.repository import Gtk

    from src.ui import window

    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _provider, _section, error: errors.append(str(error)))
    provider.load_from_path(str(Path(window.__file__).with_name("style.css")))
    assert errors == []


def test_toast_overlay_covers_the_navigation(gtk_ready, monkeypatch):
    from types import SimpleNamespace

    from gi.repository import Adw

    from src.core.context import ProxyState
    from src.ui import window

    Adw.init()
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
        assert main.toast_overlay in ancestors
    finally:
        main.destroy()


def test_form_keeps_its_default_width(gtk_ready):
    from src.ui.dialogs.base import DEFAULT_WIDTH, FormDialog

    dialog = FormDialog("Тест", "Сохранить")
    assert dialog.page.get_size_request().width == DEFAULT_WIDTH
    assert dialog.get_follows_content_size()
