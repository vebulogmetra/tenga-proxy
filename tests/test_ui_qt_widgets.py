"""Карточка состояния и тост Qt-интерфейса."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from src.ui.logic.status import ConnectionState, status_view
from src.ui.qt.widgets.status_card import StatusCard, logo_pixmap
from src.ui.qt.widgets.toast import Toast

pytestmark = pytest.mark.qt


def test_card_shows_the_connected_view(qapp):
    card = StatusCard()

    card.update_view(
        status_view(
            ConnectionState.CONNECTED,
            profile_name="Проба",
            upload_bytes=1,
            download_bytes=2,
            mode="SYSTEM",
        )
    )

    assert card.title.text() == "Подключено"
    assert card.subtitle.text() == "Проба"
    assert "SYSTEM" in card.metrics.text()
    assert card.button.text() == "Отключить"
    assert card.property("state") == "status-connected"
    assert card.button.property("role") == "destructive-action"


def test_card_hides_empty_lines(qapp):
    card = StatusCard()

    card.update_view(status_view(ConnectionState.DISCONNECTED))

    assert card.subtitle.isHidden() and card.metrics.isHidden()
    assert card.button.text() == "Подключить"


def test_card_button_emits_action(qapp):
    card = StatusCard()
    clicks = []
    card.action_clicked.connect(lambda: clicks.append(1))

    card.button.click()

    assert clicks == [1]


@pytest.mark.parametrize("state", list(ConnectionState))
def test_every_state_has_a_logo(qapp, state):
    assert not logo_pixmap(status_view(state).css_class).isNull()


def test_toast_shows_text_and_runs_the_action(qapp):
    toast = Toast()
    clicked = []

    toast.show_message(
        "Маршрутизация импортирована", button="Вернуть", on_click=lambda: clicked.append(1)
    )
    assert not toast.isHidden()
    assert toast.label.text() == "Маршрутизация импортирована"
    assert not toast.button.isHidden()

    toast.button.click()

    assert clicked == [1] and toast.isHidden()


def test_toast_without_action_has_no_button(qapp):
    toast = Toast()

    toast.show_message("Отключено")

    assert toast.button.isHidden()
