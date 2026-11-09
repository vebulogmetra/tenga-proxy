"""Tests for status card presentation logic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ui.logic.status import (
    ConnectionPresentation,
    ConnectionState,
    action_hint,
    health_text,
    is_traffic_blocked,
    mode_text,
    status_view,
)


def test_disconnected_offers_connect():
    view = status_view(ConnectionState.DISCONNECTED)
    assert view.title == "Отключено"
    assert view.subtitle == ""
    assert view.button_label == "Подключить"
    assert view.css_class == "status-disconnected"
    assert view.show_spinner is False


def test_connecting_shows_spinner_and_keeps_profile_name():
    view = status_view(ConnectionState.CONNECTING, profile_name="Польша")
    assert view.title == "Подключение…"
    assert view.subtitle == "Польша"
    assert view.show_spinner is True


def test_connecting_does_not_offer_a_cancel_it_cannot_do():
    # Контроллер не прерывает начатое подключение: кнопка «Отменить» лишь
    # показала бы тост «Подключение уже выполняется».
    view = status_view(ConnectionState.CONNECTING, profile_name="Польша")
    assert view.button_label == "Подключение…"
    assert view.action_enabled is False


def test_only_connecting_disables_the_action():
    for state in (
        ConnectionState.DISCONNECTED,
        ConnectionState.CONNECTED,
        ConnectionState.ERROR,
    ):
        assert status_view(state).action_enabled is True


def test_connected_shows_profile_and_destructive_button():
    view = status_view(ConnectionState.CONNECTED, profile_name="Германия")
    assert view.title == "Подключено"
    assert view.subtitle == "Германия"
    assert view.button_label == "Отключить"
    assert view.css_class == "status-connected"
    assert view.show_spinner is False


def test_connected_without_profile_falls_back():
    view = status_view(ConnectionState.CONNECTED, profile_name="")
    assert view.subtitle == "Сервер неизвестен"


def test_error_keeps_the_server_in_the_subtitle():
    # Причина ошибки — в строке проверки (`health_text`), там же, где и в Qt.
    view = status_view(ConnectionState.ERROR, profile_name="Польша")
    assert view.title == "Ошибка"
    assert view.subtitle == "Польша"
    assert view.css_class == "status-error"
    assert view.button_label == "Повторить"


def test_every_state_has_an_icon():
    for state in ConnectionState:
        assert status_view(state).icon_name


def test_metric_items_list_every_known_value():
    view = status_view(
        ConnectionState.CONNECTED, latency_ms=132, upload_bytes=1258291, download_bytes=51065651
    )
    assert view.metric_items == (
        ("Задержка", "132 мс"),
        ("↓ Получено", "48.7 MB"),
        ("↑ Отправлено", "1.2 MB"),
    )


def test_metric_items_skip_unknown_values():
    view = status_view(ConnectionState.CONNECTED, latency_ms=-1, upload_bytes=0, download_bytes=0)
    assert [caption for caption, _ in view.metric_items] == ["↓ Получено", "↑ Отправлено"]
    assert status_view(ConnectionState.CONNECTED).metric_items == ()


def test_mode_names_are_shared():
    assert mode_text("system") == "Режим Системный прокси"
    assert mode_text("tun") == "Режим TUN"


def test_only_the_connected_logo_is_in_colour():
    for state in ConnectionState:
        assert status_view(state).logo_desaturated is (state is not ConnectionState.CONNECTED)


@pytest.mark.parametrize(
    ("state", "hint"),
    [
        (ConnectionState.DISCONNECTED, "Нажмите на логотип для подключения"),
        (ConnectionState.CONNECTED, "Нажмите на логотип для отключения"),
        (ConnectionState.ERROR, "Нажмите на логотип для повторного подключения"),
        (ConnectionState.CONNECTING, "Подключение…"),
    ],
)
def test_action_hint_explains_the_logo(state, hint):
    assert action_hint(status_view(state)) == hint


# --- ConnectionPresentation ---


def _resolve(presentation, **overrides):
    values = {
        "running": False,
        "active_id": None,
        "busy": False,
        "profile_name": "",
        "mode": "",
        "upload": 0,
        "download": 0,
        "latency": None,
    }
    values.update(overrides)
    return presentation.resolve(**values)


def test_disconnected_names_the_profile_the_button_would_connect():
    view = _resolve(ConnectionPresentation(), profile_name="Польша")
    assert view.title == "Отключено"
    assert view.subtitle == "Польша"


def test_an_error_survives_an_unrelated_refresh():
    presentation = ConnectionPresentation()
    presentation.fail("xray-core не запустился", (False, None))

    _resolve(presentation)
    view = _resolve(presentation)

    assert view.title == "Ошибка"
    assert view.button_label == "Повторить"
    assert presentation.error == "xray-core не запустился"


def test_an_error_names_the_server_that_failed():
    presentation = ConnectionPresentation()
    presentation.fail("xray-core не запустился", (False, None))

    assert _resolve(presentation, profile_name="Польша").subtitle == "Польша"


def test_empty_store_asks_to_add_a_server():
    view = _resolve(ConnectionPresentation(), has_profiles=False, can_connect=False)

    assert view.title == "Добавьте сервер или подписку"
    assert view.action_enabled is False
    assert action_hint(view) == "Сначала добавьте или выберите сервер"


def test_nothing_to_connect_disables_the_action():
    assert _resolve(ConnectionPresentation(), can_connect=False).action_enabled is False
    assert _resolve(ConnectionPresentation(), running=True, can_connect=False).action_enabled


def test_an_error_is_cleared_when_the_connection_comes_up():
    presentation = ConnectionPresentation()
    presentation.fail("xray-core не запустился", (False, None))

    assert _resolve(presentation, running=True, active_id=3).title == "Подключено"
    assert _resolve(presentation).title == "Отключено"


def test_a_new_attempt_clears_the_previous_error():
    presentation = ConnectionPresentation()
    presentation.fail("xray-core не запустился", (False, None))
    presentation.begin("connect", "Польша")

    view = _resolve(presentation, busy=True)

    assert view.title == "Подключение…"
    assert view.subtitle == "Польша"
    assert view.action_enabled is False


def test_reconnect_after_a_network_change_names_the_reason():
    from src.ui.logic.status import RECONNECT_NETWORK, connecting_view

    presentation = ConnectionPresentation()
    presentation.begin("connect", "Польша", RECONNECT_NETWORK)

    view = _resolve(presentation, busy=True, running=True)

    assert view.title == RECONNECT_NETWORK
    assert view.subtitle == "Польша"
    assert view.button_label == "Подключение…"
    assert connecting_view("Польша", RECONNECT_NETWORK).title == RECONNECT_NETWORK
    assert connecting_view("Польша").title == "Подключение…"

    # Подключение закончилось — заголовок не переживает его.
    _resolve(presentation, busy=False, running=True)
    assert presentation.note == ""


def test_a_busy_running_session_without_a_connect_is_disconnecting():
    # GTK не сообщает о начале отключения: занятый поток при работающем
    # прокси и без начатого подключения — это отключение.
    view = _resolve(ConnectionPresentation(), busy=True, running=True, profile_name="Польша")

    assert view.title == "Отключение…"
    assert view.button_label == "Отключение…"
    assert view.action_enabled is False


def test_a_switch_is_shown_as_connecting():
    presentation = ConnectionPresentation()
    presentation.begin("connect", "Германия")

    view = _resolve(presentation, busy=True, running=True, profile_name="Польша")

    assert view.title == "Подключение…"
    assert view.subtitle == "Германия"


# --- проверка соединения ---


def test_health_is_silent_without_a_session():
    assert health_text(running=False, checked=False, proxy_ok=False, last_check="—") == ""


def test_a_started_session_is_not_called_checked():
    # «Подключено» значит только «процесс запущен»: про проверку — отдельно.
    text = health_text(running=True, checked=False, proxy_ok=True, last_check="12:00:00")
    assert text == "Проверка соединения ещё не выполнена"


def test_a_failed_check_is_named():
    text = health_text(running=True, checked=True, proxy_ok=False, last_check="12:00:00")
    assert text == "Прокси запущен, соединение не прошло проверку"


def test_a_passed_check_shows_its_time():
    text = health_text(running=True, checked=True, proxy_ok=True, last_check="12:00:00")
    assert text == "Последняя проверка соединения: 12:00:00"


def test_a_failure_takes_over_the_health_line():
    for running in (False, True):
        text = health_text(
            running=running, checked=True, proxy_ok=True, last_check="12:00:00", error="сбой"
        )
        assert text == "сбой"


def test_a_check_of_the_previous_session_does_not_count():
    presentation = ConnectionPresentation()
    assert presentation.check_done(running=True, active_id=1, last_check_time=100.0) is False
    assert presentation.check_done(running=True, active_id=1, last_check_time=150.0) is True
    # Новая сессия: прежняя проверка относится к другому подключению.
    assert presentation.check_done(running=True, active_id=2, last_check_time=150.0) is False


# --- трафик заблокирован ---


def _resolve_blocked(presentation=None, **overrides):
    arguments = {
        "running": False,
        "active_id": None,
        "busy": False,
        "profile_name": "Польша",
        "mode": "TUN",
        "upload": 0,
        "download": 0,
        "latency": None,
        "blocked": True,
    }
    arguments.update(overrides)
    return (presentation or ConnectionPresentation()).resolve(**arguments)


def test_blocked_view_names_the_state_and_the_action():
    view = status_view(ConnectionState.BLOCKED, profile_name="Польша")

    assert view.title == "Трафик заблокирован"
    assert view.subtitle == "Польша"
    assert view.button_label == "Переподключить"
    assert view.css_class == "status-blocked"
    assert view.action_enabled


def test_blocked_hint_says_which_server_the_logo_connects():
    view = status_view(ConnectionState.BLOCKED, profile_name="Польша")

    assert "прошлого сеанса" in action_hint(view)


def test_blocked_is_more_important_than_an_error():
    presentation = ConnectionPresentation()
    presentation.fail("причина", (False, None))

    assert _resolve_blocked(presentation).title == "Трафик заблокирован"


def test_running_session_is_not_shown_as_blocked():
    view = _resolve_blocked(running=True, active_id=1)

    assert view.title == "Подключено"


def test_connecting_while_blocked_shows_the_attempt():
    view = _resolve_blocked(busy=True)

    assert view.title == "Подключение…"


def test_blocked_stays_clickable_without_a_selection():
    view = _resolve_blocked(can_connect=False, has_profiles=False)

    assert view.action_enabled
    assert view.title == "Трафик заблокирован"


@pytest.mark.parametrize(
    ("traffic_blocked", "is_running", "expected"),
    [(True, False, True), (True, True, False), (False, False, False)],
)
def test_traffic_is_blocked_only_without_a_session(traffic_blocked, is_running, expected):
    state = SimpleNamespace(traffic_blocked=traffic_blocked, is_running=is_running)

    assert is_traffic_blocked(state) is expected
