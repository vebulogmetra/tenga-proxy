"""Platform stylesheet loading and GTK CSS syntax."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


@pytest.mark.parametrize("windows", [False, True])
def test_platform_stylesheets(monkeypatch, windows):
    from src.core import platform_info
    from src.ui import window

    loaded = []
    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
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
    from gi.repository import Gdk

    texture = label._flag.get_paintable()
    assert isinstance(texture, Gdk.Texture)
    assert (texture.get_width(), texture.get_height()) == (32, 24)

    label.set_text("Без флага")
    assert label._label.get_text() == "Без флага"
    assert not label._flag.get_visible()

    label.set_text("🇿🇿Неизвестно")
    assert label._label.get_text() == "🇿🇿Неизвестно"
    assert not label._flag.get_visible()


def test_windows_name_label_keeps_text_when_bitmap_is_invalid(gtk_ready, monkeypatch, tmp_path):
    from src.ui.widgets import name_label

    broken = tmp_path / "ru.bmp"
    broken.write_bytes(b"invalid image")
    monkeypatch.setattr(name_label, "get_asset_path", lambda _name: broken)
    label = name_label.FlagNameLabel()
    label.set_text("🇷🇺Москва")
    assert label._label.get_text() == "🇷🇺Москва"
    assert not label._flag.get_visible()
    assert label._flag.get_paintable() is None


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

    from src.core import platform_info
    from src.core.context import ProxyState
    from src.ui import window

    Adw.init()
    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
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


@pytest.mark.parametrize("windows", [False, True])
def test_form_width_can_adapt_on_windows(gtk_ready, monkeypatch, windows):
    from src.core import platform_info
    from src.ui.dialogs.base import DEFAULT_WIDTH, FormDialog

    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
    dialog = FormDialog("Тест", "Сохранить")
    if windows:
        assert dialog.page.get_size_request().width == -1
        assert not dialog.get_follows_content_size()
        assert dialog.get_content_width() == 560
    else:
        assert dialog.page.get_size_request().width == DEFAULT_WIDTH
        assert dialog.get_follows_content_size()


@pytest.mark.parametrize("windows", [False, True])
def test_diagnostics_actions_can_wrap_on_windows(gtk_ready, monkeypatch, windows):
    from gi.repository import Gtk

    from src.core import platform_info
    from src.ui.pages.monitoring import MonitoringPage

    monkeypatch.setattr(platform_info, "IS_WINDOWS", windows)
    page = MonitoringPage()

    def descendants(widget):
        child = widget.get_first_child()
        while child is not None:
            yield child
            yield from descendants(child)
            child = child.get_next_sibling()

    groups = [w for w in descendants(page) if w.has_css_class("diagnostic-actions")]
    assert len(groups) == int(windows)
    if windows:
        assert isinstance(groups[0], Gtk.FlowBox)
        assert groups[0].get_min_children_per_line() == 1
