"""Tests for the status card widget."""

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


def test_update_shows_title_and_subtitle(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="Германия"))

    assert card.get_title() == "Подключено"
    assert card.get_subtitle() == "Германия"


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


def test_button_css_class_replaces_the_previous_one(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert "destructive-action" in card.action_button.get_css_classes()

    card.update(_view(ConnectionState.DISCONNECTED))
    classes = card.action_button.get_css_classes()
    assert "suggested-action" in classes
    assert "destructive-action" not in classes


def test_spinner_visible_only_while_connecting(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.is_spinning() is True

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.is_spinning() is False


def test_metrics_row_hidden_when_empty(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.get_metrics() == ""

    card.update(
        _view(
            ConnectionState.CONNECTED,
            profile_name="X",
            latency_ms=132,
            upload_bytes=0,
            download_bytes=0,
            mode="TUN",
        )
    )
    assert "132 ms" in card.get_metrics()


def test_logo_replaces_the_themed_icon_when_connected(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.shows_logo() is True

    # У ошибки логотипа нет: предупреждение читается однозначнее.
    card.update(_view(ConnectionState.ERROR, error="boom"))
    assert card.shows_logo() is False


def test_button_click_emits_signal(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    seen = []
    card.connect("action-clicked", lambda _card: seen.append(True))

    card.action_button.emit("clicked")

    assert seen == [True]
