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


def test_spinner_visible_only_while_connecting(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.is_spinning() is True

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.is_spinning() is False


def test_logo_button_explains_its_action(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.logo_button.get_tooltip_text() == "Нажмите на логотип для подключения"


def test_warning_is_shown_only_for_an_error(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.ERROR, profile_name="X"))
    assert card._warning.get_visible() is True

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card._warning.get_visible() is False


def test_button_is_insensitive_while_connecting(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.logo_button.get_sensitive() is False

    card.update(_view(ConnectionState.ERROR, profile_name="X"))
    assert card.logo_button.get_sensitive() is True


def test_switch_button_names_its_target_in_the_tooltip(card):
    card.set_switch_target("Германия", enabled=True)
    assert card.switch_button.get_visible() is True
    assert card.switch_button.get_label() == "Переключить на выбранный"
    assert card.switch_button.get_tooltip_text() == "Подключить: Германия"

    card.set_switch_target("", enabled=True)
    assert card.switch_button.get_visible() is False


def test_switch_button_emits_its_own_signal(card):
    seen = []
    card.connect("switch-clicked", lambda _card: seen.append("switch"))
    card.connect("action-clicked", lambda _card: seen.append("action"))
    card.set_switch_target("Германия", enabled=True)

    card.switch_button.emit("clicked")

    assert seen == ["switch"]


def test_health_row_hidden_when_empty(card):
    card.set_health("")
    assert card.get_health() == ""
    card.set_health("Проверка соединения ещё не выполнена")
    assert card.get_health() == "Проверка соединения ещё не выполнена"


def test_metrics_and_mode_follow_the_view(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.get_metrics() == []
    assert card._metrics.get_visible() is False

    card.update(
        _view(
            ConnectionState.CONNECTED,
            profile_name="X",
            latency_ms=132,
            upload_bytes=0,
            download_bytes=0,
            mode="Режим TUN",
        )
    )
    assert card.get_metrics() == ["Задержка 132 мс", "↓ Получено 0 B", "↑ Отправлено 0 B"]
    assert card.get_mode() == "Режим TUN"

    # Значение исчезает, а ячейка остаётся на следующий тик счётчика.
    card.update(
        _view(ConnectionState.CONNECTED, profile_name="X", upload_bytes=1, download_bytes=1)
    )
    assert [text.split()[1] for text in card.get_metrics()] == ["Получено", "Отправлено"]


def test_the_logo_stays_in_every_state(card):
    from src.ui.logic.status import ConnectionState

    for state in ConnectionState:
        card.update(_view(state))
        assert card.shows_logo() is True


def test_button_click_emits_signal(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.DISCONNECTED))
    seen = []
    card.connect("action-clicked", lambda _card: seen.append(True))

    card.logo_button.emit("clicked")

    assert seen == [True]
