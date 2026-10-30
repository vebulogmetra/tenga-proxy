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
            latency_ms=209,
            upload_bytes=1,
            download_bytes=2,
            mode="SYSTEM",
        )
    )

    assert card.title.text() == "Подключено"
    assert card.subtitle.text() == "Проба"
    assert [value.text() for _, value in card.metric_values] == ["209 мс", "2 B", "1 B"]
    assert card.instruction.isHidden()
    assert card.logo.toolTip() == "Нажмите на логотип для отключения"
    assert card.logo.accessibleName() == "Отключить"
    assert card.instruction.text() == "Нажмите на логотип для отключения"
    assert card.property("state") == "status-connected"


def test_card_hides_empty_lines(qapp):
    card = StatusCard()

    card.update_view(status_view(ConnectionState.DISCONNECTED))

    assert card.subtitle.isHidden() and card.metrics.isHidden()
    assert card.instruction.text() == "Нажмите на логотип для подключения"


def test_card_button_emits_action(qapp):
    card = StatusCard()
    clicks = []
    card.action_clicked.connect(lambda: clicks.append(1))

    card.logo.click()

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


@pytest.mark.parametrize("compact", [False, True])
def test_connected_card_separates_profile_and_metrics(qapp, compact):
    card = StatusCard()
    card.resize(900, 280)
    card.set_compact(compact)
    card.update_view(
        status_view(
            ConnectionState.CONNECTED,
            profile_name="Финляндия | Тестовый сервер",
            latency_ms=209,
            upload_bytes=1024,
            download_bytes=2048,
        ),
        mode="TUN",
    )
    card.show()
    qapp.processEvents()
    assert card.mode.text() == "Режим TUN"
    assert card.metrics.isVisible()
    assert not card.instruction.isVisible()
    if not compact:
        assert card.name_box.geometry().bottom() < card.logo.geometry().top()
        assert card.metrics.geometry().top() > card.text_box.geometry().bottom()
    assert [value.text() for _, value in card.metric_values] == ["209 мс", "2.0 KB", "1.0 KB"]
    card.close()
