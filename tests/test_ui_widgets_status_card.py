"""Tests for the status panel widget."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


@pytest.fixture
def card(gtk_ready):
    from src.ui.widgets.status_card import StatusCard

    return StatusCard()


def _view(state, **kwargs):
    from src.ui.logic.status import status_view

    return status_view(state, **kwargs)


def test_glow_follows_the_state_colour(gtk_ready):
    from src.ui.widgets.logo_glow import LogoGlow

    glow = LogoGlow()
    assert glow.get_color_for_test() is None

    glow.set_color("#5ed3c7")
    assert glow.get_color_for_test() == "#5ed3c7"
    assert glow.get_visible() is True

    glow.set_color(None)
    assert glow.get_visible() is False


def test_card_is_a_vertical_panel_with_glow(card):
    from gi.repository import Gtk

    from src.ui.logic.status import ConnectionState
    from src.ui.widgets.logo_glow import LogoGlow

    assert card.get_orientation() == Gtk.Orientation.VERTICAL
    assert isinstance(card.glow, LogoGlow)

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.glow.get_color_for_test() == "#5ed3c7"
    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.glow.get_color_for_test() == "#ffa64d"
    card.update(_view(ConnectionState.ERROR, profile_name="X"))
    assert card.glow.get_color_for_test() == "#e07078"
    card.update(_view(ConnectionState.BLOCKED, profile_name="X"))
    assert card.glow.get_color_for_test() == "#e07078"
    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.glow.get_color_for_test() is None


def test_card_has_no_badges_over_the_logo(card):
    assert not hasattr(card, "_spinner")
    assert not hasattr(card, "_warning")
    assert not hasattr(card, "is_spinning")


def test_update_shows_title_and_subtitle(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="Германия"))

    assert card.get_title() == "Подключено"
    assert card.get_subtitle() == "Германия"


def test_flag_is_split_from_the_name(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="🇩🇪 Берлин"))
    assert card.get_subtitle() == "Берлин"
    assert card.flag.get_visible() is True
    assert card.subtitle_label.get_tooltip_text() == "🇩🇪 Берлин"

    card.update(_view(ConnectionState.CONNECTED, profile_name="Берлин"))
    assert card.flag.get_visible() is False


def test_instruction_and_dot_follow_the_state(card):
    from src.ui.logic.status import ConnectionState, action_hint

    view = _view(ConnectionState.CONNECTED, profile_name="X")
    card.update(view)
    assert card.get_instruction() == action_hint(view)
    assert "status-connected" in card.dot.get_css_classes()
    assert card.get_server_caption() == "Активный сервер"

    card.update(_view(ConnectionState.DISCONNECTED, profile_name="X"))
    assert card.get_server_caption() == "Сервер"
    assert "status-connected" not in card.dot.get_css_classes()
    assert "status-disconnected" in card.dot.get_css_classes()


def test_server_caption_hides_without_a_server(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.server_caption.get_visible() is False


def test_metrics_are_columns_and_empty_ones_hide(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X", latency_ms=42))
    assert card.get_metrics() == [("Задержка", "42 мс")]

    card.update(
        _view(ConnectionState.CONNECTED, profile_name="X", upload_bytes=12, download_bytes=128)
    )
    assert [caption for caption, _ in card.get_metrics()] == ["↓ Получено", "↑ Отправлено"]
    assert card.get_mode() == ""

    card.update(_view(ConnectionState.CONNECTED, profile_name="X", mode="Режим TUN"))
    assert card.get_mode() == "Режим TUN"
    assert card.get_metrics() == []


def test_compact_mode_shrinks_the_logo(card):
    from src.ui.logic.appearance import LOGO_SIZE, LOGO_SIZE_COMPACT

    assert card.logo_image.get_pixel_size() == LOGO_SIZE
    card.set_property("compact", True)
    assert card.logo_image.get_pixel_size() == LOGO_SIZE_COMPACT
    assert "compact" in card.get_css_classes()
    card.set_property("compact", False)
    assert card.logo_image.get_pixel_size() == LOGO_SIZE
    assert "compact" not in card.get_css_classes()


def test_card_no_longer_owns_the_switch_button(card):
    assert not hasattr(card, "switch_button")
    assert not hasattr(card, "set_switch_target")


def test_button_label_follows_state(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.get_button_label() == "Подключить"

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.get_button_label() == "Отключить"


def test_state_css_class_replaces_the_previous_one(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert "status-connected" in card.get_css_classes()

    card.update(_view(ConnectionState.DISCONNECTED))
    classes = card.get_css_classes()
    assert "status-disconnected" in classes
    assert "status-connected" not in classes


def test_logo_button_explains_its_action(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.logo_button.get_tooltip_text() == "Нажмите на логотип для подключения"


def test_button_is_insensitive_while_connecting(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.logo_button.get_sensitive() is False

    card.update(_view(ConnectionState.ERROR, profile_name="X"))
    assert card.logo_button.get_sensitive() is True


def test_health_row_hidden_when_empty(card):
    card.set_health("")
    assert card.get_health() == ""
    assert card.health_label.get_visible() is False
    card.set_health("Проверка соединения ещё не выполнена")
    assert card.get_health() == "Проверка соединения ещё не выполнена"
    assert card.health_label.get_visible() is True


def test_the_logo_stays_in_every_state(card):
    from src.ui.logic.status import ConnectionState

    for state in ConnectionState:
        card.update(_view(state))
        assert card.shows_logo() is True


def test_logo_is_desaturated_unless_connected(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    colour = card.logo_image.get_paintable()
    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.logo_image.get_paintable() is not colour


def test_button_click_emits_signal(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    seen = []
    card.connect("action-clicked", lambda _card: seen.append(True))

    card.logo_button.emit("clicked")

    assert seen == [True]


def test_panel_keeps_its_minimum_width(card):
    from src.ui.logic.appearance import PANEL_MIN_WIDTH

    assert card.get_size_request()[0] == PANEL_MIN_WIDTH
