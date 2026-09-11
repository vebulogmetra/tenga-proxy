"""Tests for status card presentation logic."""

from __future__ import annotations

from src.ui.logic.status import ConnectionState, metrics_text, status_view


def test_disconnected_offers_connect():
    view = status_view(ConnectionState.DISCONNECTED)
    assert view.title == "Отключено"
    assert view.subtitle == ""
    assert view.button_label == "Подключить"
    assert view.button_class == "suggested-action"
    assert view.css_class == "status-disconnected"
    assert view.show_spinner is False


def test_connecting_shows_spinner_and_keeps_profile_name():
    view = status_view(ConnectionState.CONNECTING, profile_name="Польша")
    assert view.title == "Подключение…"
    assert view.subtitle == "Польша"
    assert view.show_spinner is True
    assert view.button_label == "Отменить"


def test_connected_shows_profile_and_destructive_button():
    view = status_view(ConnectionState.CONNECTED, profile_name="Германия")
    assert view.title == "Подключено"
    assert view.subtitle == "Германия"
    assert view.button_label == "Отключить"
    assert view.button_class == "destructive-action"
    assert view.css_class == "status-connected"
    assert view.show_spinner is False


def test_connected_without_profile_falls_back():
    view = status_view(ConnectionState.CONNECTED, profile_name="")
    assert view.subtitle == "Профиль неизвестен"


def test_error_shows_message_as_subtitle():
    view = status_view(ConnectionState.ERROR, error="xray-core не запустился")
    assert view.title == "Ошибка"
    assert view.subtitle == "xray-core не запустился"
    assert view.css_class == "status-error"
    assert view.button_label == "Подключить"


def test_error_without_message_has_generic_subtitle():
    assert status_view(ConnectionState.ERROR).subtitle == "Соединение не установлено"


def test_every_state_has_an_icon():
    for state in ConnectionState:
        assert status_view(state).icon_name


def test_metrics_text_joins_all_known_parts():
    text = metrics_text(latency_ms=132, upload_bytes=1258291, download_bytes=51065651, mode="TUN")
    assert text == "132 ms · ↑ 1.2 MB ↓ 48.7 MB · TUN"


def test_metrics_text_skips_unknown_latency():
    text = metrics_text(latency_ms=None, upload_bytes=0, download_bytes=0, mode="TUN")
    assert text == "↑ 0 B ↓ 0 B · TUN"


def test_metrics_text_skips_negative_latency():
    assert metrics_text(latency_ms=-1, upload_bytes=0, download_bytes=0, mode="") == "↑ 0 B ↓ 0 B"


def test_metrics_text_is_empty_when_nothing_is_known():
    assert metrics_text(latency_ms=None, upload_bytes=None, download_bytes=None, mode="") == ""


def test_connected_shows_the_logo_in_colour():
    view = status_view(ConnectionState.CONNECTED, profile_name="Польша")

    assert view.use_logo is True
    assert view.logo_desaturated is False


def test_disconnected_shows_the_logo_desaturated():
    view = status_view(ConnectionState.DISCONNECTED)

    assert view.use_logo is True
    assert view.logo_desaturated is True


def test_connecting_and_error_keep_their_themed_icons():
    # Спиннер и предупреждение сообщают состояние точнее, чем логотип.
    for state in (ConnectionState.CONNECTING, ConnectionState.ERROR):
        assert status_view(state).use_logo is False
