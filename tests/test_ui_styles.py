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
