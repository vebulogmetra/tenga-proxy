"""Контракт действий и состояний центрального монолита Windows."""

from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest

from src.core.connection import ConnectionResult
from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.logic.latency import PingProgress
from src.ui.logic.profiles_view import SortKey
from src.ui.qt.application import QtApplication
from tests.support.qt import process_events, wait_until
from tests.test_ui_qt_application import FakeService

pytestmark = pytest.mark.qt
LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#"


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    context.config.monitoring_panel = False
    app = QtApplication(context, with_tray=False)
    app.set_connection_service(FakeService(context))
    yield app
    if app.controller.connection_thread is not None:
        app.controller.connection_thread.join(4)
    if app.current_dialog is not None:
        app.current_dialog.reject()
    if app.window is not None:
        app.window.detach()
        app.window.deleteLater()
    process_events()


def add(app, name="Берлин"):
    return app.controller.add_profile_from_bean(parse_link(LINK + name))


def select(app, entry):
    app.window.tree.setCurrentIndex(app.window.model.profile_index(entry.id))


def settled(app):
    if app.controller.connection_thread is not None:
        app.controller.connection_thread.join(3)
    for _ in range(5):
        process_events()


def test_empty_and_selected_target(app):
    app.activate()
    card = app.window.status_card
    assert not card.logo.isEnabled()
    assert "Добавьте" in card.title.text()
    entry = add(app)
    select(app, entry)
    assert card.logo.isEnabled()
    assert card.subtitle.text() == entry.name
    assert card.logo.accessibleName() == "Подключить"
    assert card.instruction.text() == "Нажмите на логотип для подключения"
    assert card.health.isHidden()


def test_logo_runs_the_action_once(app):
    entry = add(app)
    service = FakeService(app.context)
    app.set_connection_service(service)
    app.activate()
    select(app, entry)
    app.window.status_card.logo.click()
    settled(app)
    assert service.calls == [("connect", entry.id)]
    assert app.window.status_card.title.text() == "Подключено"
    app.window.status_card.logo.click()
    settled(app)
    assert service.calls == [("connect", entry.id), ("disconnect",)]


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return])
def test_logo_is_a_keyboard_button(app, key):
    entry = add(app)
    app.activate()
    select(app, entry)
    app.window.status_card.logo.setFocus()
    QTest.keyClick(app.window.status_card.logo, key)
    settled(app)
    assert app.context.proxy_state.started_profile_id == entry.id


def test_last_used_target_is_visible_without_selection(app):
    entry = add(app)
    app.context.profiles.mark_used(entry.id)
    app.activate()
    assert app.window.selected_profile_id() is None
    assert app.window.status_card.subtitle.text() == entry.name
    assert app.window.status_card.logo.isEnabled()


def test_selection_does_not_change_active_and_switch_is_explicit(app):
    first = add(app, "Берлин")
    second = add(app, "Прага")
    app.activate()
    app.context.proxy_state.set_running(first.id, mode="system")
    process_events()
    select(app, second)
    assert app.context.proxy_state.started_profile_id == first.id
    assert app.window.status_card.subtitle.text() == first.name
    assert app.window.status_card.mode.text() == "Режим Системный прокси"
    assert app.window.switch_button.isVisible()
    assert (
        "Подключён"
        in app.window.model.itemFromIndex(app.window.model.profile_index(first.id)).text()
    )
    app.window.switch_button.click()
    settled(app)
    assert app.context.proxy_state.started_profile_id == second.id
    assert not app.window.switch_button.isVisible()


def test_failed_switch_keeps_real_active_session_and_error(app):
    first = add(app, "Берлин")
    second = add(app, "Прага")
    app.activate()
    app.context.proxy_state.set_running(first.id, mode="system")
    app.set_connection_service(
        SimpleNamespace(connect=lambda _id: ConnectionResult(False, "Тестовый отказ"))
    )
    select(app, second)
    app.window.switch_button.click()
    settled(app)
    assert app.window.status_card.title.text() == "Подключено"
    assert app.window.status_card.subtitle.text() == first.name
    assert app.window.status_card.logo.accessibleName() == "Отключить"
    assert "Тестовый отказ" in app.window.status_card.health.text()


def test_error_survives_unrelated_refresh_and_clears_on_retry(app):
    entry = add(app)
    app.activate()
    select(app, entry)
    app.window.show_error("Сервер не ответил")
    app.window.refresh_pages()
    app.window.refresh_monitoring()
    assert app.window.status_card.title.text() == "Ошибка"
    assert app.window.status_card.logo.accessibleName() == "Повторить"
    app.window.status_card.logo.click()
    settled(app)
    assert not app.window.presentation.error
    assert app.window.status_card.title.text() == "Подключено"


@pytest.mark.parametrize("operation", ["connect", "disconnect"])
def test_busy_disables_controls_and_prevents_duplicates(app, operation):
    entry = add(app)
    app.activate()
    select(app, entry)
    release = Event()
    calls = []

    def perform(*args):
        calls.append(args)
        release.wait(3)
        if operation == "connect":
            app.context.proxy_state.set_running(entry.id)
        else:
            app.context.proxy_state.set_stopped()
        return ConnectionResult(True)

    app.set_connection_service(SimpleNamespace(connect=perform, disconnect=perform))
    if operation == "disconnect":
        app.context.proxy_state.set_running(entry.id)
        process_events()
    try:
        app.window.status_card.logo.click()
        wait_until(lambda: len(calls) == 1)
        card = app.window.status_card
        assert not card.logo.isEnabled()
        assert card.instruction.text() == (
            "Подключение…" if operation == "connect" else "Отключение…"
        )
        card.logo.click()
        app.activate_action("connect-profile", entry.id)
        assert len(calls) == 1
    finally:
        release.set()
        settled(app)


def test_failed_disconnect_does_not_claim_stopped(app):
    entry = add(app)
    app.activate()
    app.context.proxy_state.set_running(entry.id)
    process_events()
    app.set_connection_service(SimpleNamespace(disconnect=lambda: ConnectionResult(False, "Отказ")))
    app.window.status_card.logo.click()
    settled(app)
    assert app.window.status_card.title.text() == "Подключено"
    assert "Не удалось отключиться" in app.window.status_card.health.text()


def test_diagnostics_reuses_widgets_and_changes_placement(app):
    app.activate()
    window = app.window
    window.resize(1180, 950)
    window.monitoring_button.setChecked(True)
    process_events()
    assert window.monitoring_body.parent() is window.centralWidget()
    label = window._monitoring_values["0"]
    window.refresh_monitoring()
    assert label is window._monitoring_values["0"]
    window.resize(900, 600)
    process_events()
    assert window.monitoring_body.parent() is window.monitoring_window
    assert window.monitoring_window.isVisible()
    window.monitoring_window.close()
    assert not window.monitoring_button.isChecked()
    assert not app.context.config.monitoring_panel


def test_compact_mode_has_hysteresis_and_centered_logo(app):
    add(app)
    app.activate()
    window = app.window
    window.resize(1180, 900)
    process_events()
    assert not window.status_card.compact
    window.resize(900, 600)
    process_events()
    assert window.status_card.compact
    window.resize(1000, 740)
    process_events()
    assert window.status_card.compact
    window.resize(1180, 900)
    process_events()
    assert not window.status_card.compact
    card = window.status_card
    assert abs(card.logo.geometry().center().x() - card.rect().center().x()) <= 2


def test_long_name_fits_compact_card_and_flag_stays_with_name(app):
    entry = add(app, "🇩🇪 " + "Очень длинное имя сервера " * 12)
    app.activate()
    select(app, entry)
    app.window.resize(900, 600)
    process_events()
    card = app.window.status_card
    assert app.window.width() == 900
    assert card.name_box.width() <= card.text_box.width()
    assert card.subtitle.text().endswith("…")
    assert card.subtitle.toolTip() == entry.name
    assert abs(card.logo.geometry().center().x() - card.rect().center().x()) <= 2


def test_session_health_does_not_reuse_previous_check(app):
    entry = add(app)
    status = SimpleNamespace(
        proxy_ok=True, vpn_ok=True, last_check_time=100, proxy_error="", vpn_error=""
    )
    app.activate()
    app.context.set_monitor(SimpleNamespace(status=status))
    app.context.proxy_state.set_running(entry.id)
    process_events()
    assert "ещё не выполнена" in app.window.status_card.health.text()
    status.last_check_time = 101
    app.window.refresh_monitoring()
    assert app.window.status_card.health.isHidden()
    assert "Последняя проверка" in app.window.last_check.text()
    app.context.set_monitor(None)


def test_batch_updates_preserve_order_selection_and_scroll(app):
    entries = [add(app, f"Сервер {i:03}") for i in range(60)]
    app.activate()
    window = app.window
    select(app, entries[35])
    window.set_sort(SortKey.PING)
    progress = PingProgress({entries[0].group_id: [entry.id for entry in entries]})
    window.set_ping_progress(progress)
    before = [window.model.item(0).child(i).data(Qt.ItemDataRole.UserRole + 2) for i in range(60)]
    bar = window.tree.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    position = bar.value()
    entries[-1].latency_ms = 1
    window.refresh_pages()
    after = [window.model.item(0).child(i).data(Qt.ItemDataRole.UserRole + 2) for i in range(60)]
    assert before == after
    assert window.selected_profile_id() == entries[35].id
    assert abs(bar.value() - position) <= 1


def test_palette_change_refreshes_cached_qss_colors(app):
    entry = add(app)
    app.activate()
    select(app, entry)
    original = app.qt.palette()
    try:
        for background, foreground in (("#ffffff", "#202020"), ("#202020", "#ffffff")):
            palette = QPalette(original)
            for role in (
                QPalette.ColorRole.Window,
                QPalette.ColorRole.Base,
                QPalette.ColorRole.Button,
            ):
                palette.setColor(role, QColor(background))
            for role in (
                QPalette.ColorRole.WindowText,
                QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText,
            ):
                palette.setColor(role, QColor(foreground))
            app.qt.setPalette(palette)
            wait_until(
                lambda foreground=foreground: app.window.status_card.title.palette().color(
                    QPalette.ColorRole.WindowText
                )
                == QColor(foreground)
            )
            assert app.window.tree.palette().color(QPalette.ColorRole.Base) == QColor(background)
    finally:
        app.qt.setPalette(original)
        process_events()


def test_header_buttons_match_and_about_is_only_in_settings(app):
    app.activate()
    process_events()
    window = app.window
    assert window.settings_button.height() == window.menu_button.height()
    assert "О программе" not in [action.text() for action in window.main_menu.actions()]
    app.activate_action("settings")
    assert "О программе" in [
        app.current_dialog.sections.item(i).text()
        for i in range(app.current_dialog.sections.count())
    ]


def test_group_progress_adds_a_bar_row_only_during_probe(app):
    entry = add(app)
    app.activate()
    tree = app.window.tree
    index = app.window.model.group_index(entry.group_id)
    tree.doItemsLayout()
    height = tree.visualRect(index).height()
    progress = PingProgress({entry.group_id: [entry.id]})
    app.window.set_ping_progress(progress)
    tree.doItemsLayout()
    assert tree.visualRect(index).height() > height
    progress.record(entry.id)
    app.window.update_group_progress(entry.group_id)
    assert "Проверено: 1 / 1" in index.data()
    app.window.set_ping_progress(None)
    tree.doItemsLayout()
    assert tree.visualRect(index).height() == height


def test_server_container_is_bounded_centered_and_can_shrink(app):
    add(app)
    app.activate()
    window = app.window
    window.resize(1920, 1000)
    process_events()
    container = window.library_container
    assert container.width() == 1000
    assert window.status_card.width() == container.width()
    assert window.status_card.geometry().left() == container.geometry().left()
    assert abs(container.geometry().center().x() - window.centralWidget().rect().center().x()) <= 2
    window.resize(900, 600)
    process_events()
    assert window.width() == 900
    assert container.width() < window.centralWidget().width()
    assert window.status_card.width() == container.width()
    assert window.status_card.geometry().left() == container.geometry().left()
    assert window.tree.parent() is window.list_box
    assert window.search.parent() is container
