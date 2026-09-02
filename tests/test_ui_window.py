"""Tests for the main window shell."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture
def window(adw_app):
    adw_app.activate()
    return adw_app.get_active_window()


def test_window_has_three_pages(window):
    names = [page.get_name() for page in window.view_stack.get_pages()]
    assert names == ["profiles", "subscriptions", "monitoring"]


def test_window_has_a_status_card(window):
    from src.ui.widgets.status_card import StatusCard

    assert isinstance(window.status_card, StatusCard)


def test_narrow_window_moves_the_switcher_down(window):
    """Проверяется поведение, а не факт установки: list_breakpoints() есть только с 1.6."""
    from gi.repository import GLib

    window.set_default_size(420, 700)
    window.present()

    context = GLib.MainContext.default()
    for _ in range(200):
        if not context.pending():
            break
        context.iteration(False)

    assert window.get_current_breakpoint() is not None
    assert window.view_switcher_bar.get_reveal() is True
    assert window.view_switcher.get_visible() is False


def test_default_size_comes_from_saved_geometry(adw_app):
    from src.ui.logic.geometry import Geometry, format_geometry

    adw_app.context.config.window_size = format_geometry(Geometry(900, 800))
    adw_app.activate()
    window = adw_app.get_active_window()

    assert window.get_default_size() == (900, 800)


def test_close_request_saves_geometry(window, adw_app):
    from src.ui.logic.geometry import parse_geometry

    window.set_default_size(880, 660)
    window.emit("close-request")

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (880, 660)


def test_status_card_follows_proxy_state(window, adw_app):
    adw_app.context.proxy_state.is_running = False
    window.refresh_status()
    assert window.status_card.get_title() == "Отключено"

    adw_app.context.proxy_state.is_running = True
    window.refresh_status()
    assert window.status_card.get_title() == "Подключено"


def test_default_width_is_wider_than_the_narrow_breakpoint():
    """Окно по умолчанию не должно открываться в компактном режиме."""
    from src.ui.logic.geometry import DEFAULT_GEOMETRY
    from src.ui.window import NARROW_WIDTH

    assert DEFAULT_GEOMETRY.width > NARROW_WIDTH


def test_geometry_is_saved_without_close_request(window, adw_app):
    """Выход по сигналу не эмитирует close-request, геометрия всё равно нужна."""
    from src.ui.logic.geometry import parse_geometry

    window.set_default_size(910, 640)
    window.save_geometry()

    saved = parse_geometry(adw_app.context.config.window_size)
    assert (saved.width, saved.height) == (910, 640)
