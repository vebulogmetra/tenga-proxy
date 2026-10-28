"""Qt-приложение поверх AppController: окно, действия, диалоги, трей."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.connection import ConnectionResult
from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.controller import CONFIRM_DELETE, CONFIRM_URL_CHANGE
from src.ui.logic.profiles_view import SortKey
from src.ui.qt.application import NOT_YET_TEXT, QtApplication
from src.ui.qt.models import PING_COLUMN
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


class FakeService:
    """Подключение без xray: только состояние прокси, как у настоящего сервиса."""

    def __init__(self, context):
        self._context = context
        self.calls = []

    def connect(self, profile_id):
        self.calls.append(("connect", profile_id))
        self._context.proxy_state.set_running(profile_id, mode="system")
        return ConnectionResult(True)

    def disconnect(self):
        self.calls.append(("disconnect",))
        self._context.proxy_state.set_stopped()
        return ConnectionResult(True)

    def shutdown(self, thread):
        self.calls.append(("shutdown",))


class FakeTrayItem:
    def __init__(self):
        self.messages = []
        self.menu = []

    def publish(self):
        pass

    def shutdown(self):
        pass

    def set_icon(self, *_args):
        pass

    def set_status(self, _status):
        pass

    def set_tooltip(self, _text):
        pass

    def set_menu(self, items):
        self.menu = items

    def set_on_activate(self, _handler):
        pass

    def set_on_primary(self, _handler):
        pass

    def show_message(self, title, text):
        self.messages.append((title, text))


@pytest.fixture
def made(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    service = FakeService(context)
    app.set_connection_service(service)
    yield app, service
    if app.window is not None:
        app.window.detach()
        app.window.deleteLater()
    if app.current_dialog is not None:
        app.current_dialog.reject()
    process_events()


def _add_profile(app, name="Проба", group_id=None):
    bean = parse_link(LINK.replace("Проба", name))
    return app.controller.add_profile_from_bean(bean, group_id=group_id)


def _wait_connection(app):
    if app.controller.connection_thread is not None:
        app.controller.connection_thread.join(5)
    wait_until(
        lambda: app.controller.connection_thread is None or not app.controller.connection_busy()
    )
    for _ in range(5):
        process_events()


def test_activate_shows_the_window_with_profiles(made):
    app, _service = made
    entry = _add_profile(app)

    app.activate()

    window = app.window
    assert window.windowTitle() == "Veblock"
    assert window.status_card.title.text() == "Отключено"
    group = window.model.item(0, 0)
    assert group.child(0, 0).text() == entry.name


def test_double_click_connects_and_the_card_follows(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()
    index = app.window.model.profile_index(entry.id)

    app.window.tree.activated.emit(index)
    _wait_connection(app)

    assert service.calls == [("connect", entry.id)]
    wait_until(lambda: app.window.status_card.title.text() == "Подключено")
    assert app.window.status_card.subtitle.text() == entry.name
    assert app.last_toast_for_test == f"Подключено: {entry.name}"


def test_toggle_action_disconnects(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()
    app.controller.context.proxy_state.set_running(entry.id, mode="system")

    app.actions["toggle-connection"].trigger()
    _wait_connection(app)

    assert service.calls == [("disconnect",)]
    wait_until(lambda: app.window.status_card.title.text() == "Отключено")


def test_tray_targets_a_profile_by_number(made):
    app, service = made
    entry = _add_profile(app)
    app.activate()

    app.activate_action("connect-profile", entry.id)
    _wait_connection(app)

    assert service.calls == [("connect", entry.id)]


def test_unknown_action_is_ignored(made):
    app, _service = made

    app.activate_action("no-such-action")


def test_dialog_actions_say_they_are_not_there_yet(made):
    app, _service = made
    app.activate()

    app.actions["settings"].trigger()

    assert app.last_toast_for_test == NOT_YET_TEXT


def test_restore_routing_follows_the_backup(made):
    app, _service = made

    assert not app.actions["restore-routing"].isEnabled()


def test_confirm_runs_only_on_the_accept_button(made):
    app, _service = made
    app.activate()
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_DELETE,
        "Оставить?",
        "Текст",
        lambda: confirmed.append(1),
        confirm_label="Оставить рабочие",
    )
    box = app.current_dialog
    assert isinstance(box, QMessageBox)
    labels = [button.text() for button in box.buttons()]
    assert "Оставить рабочие" in labels and "Отмена" in labels
    # Второй диалог поверх первого не открывается.
    assert app.present_dialog(QMessageBox()) is False

    box.defaultButton().click()
    process_events()
    assert confirmed == []
    assert app.current_dialog is None


def test_confirm_accept_calls_back(made):
    app, _service = made
    app.activate()
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: confirmed.append(1)
    )
    box = app.current_dialog
    accept = next(b for b in box.buttons() if b.text() == "Сменить")
    accept.click()
    process_events()

    assert confirmed == [1]


def test_toast_button_runs_its_action(made):
    app, _service = made
    app.activate()
    seen = []
    app._handlers["restore-routing"] = lambda _target: seen.append(1)

    app.controller.toast(
        "Маршрутизация импортирована", button="Вернуть", action="app.restore-routing"
    )
    app.window.toast_widget.button.click()

    assert seen == [1]


def test_search_filters_the_tree(made):
    app, _service = made
    _add_profile(app, "Альфа")
    _add_profile(app, "Бета")
    app.activate()

    app.window.search.setText("бета")

    group = app.window.model.item(0, 0)
    assert [group.child(i, 0).text() for i in range(group.rowCount())] == ["Бета"]


def test_ping_header_sorts_by_latency(made):
    app, _service = made
    fast = _add_profile(app, "Быстрый")
    slow = _add_profile(app, "Медленный")
    fast.latency_ms, slow.latency_ms = 10, 90
    app.activate()

    app.window._on_header_clicked(PING_COLUMN)
    app.window._on_header_clicked(PING_COLUMN)

    group = app.window.model.item(0, 0)
    assert app.window._sort_key is SortKey.PING
    assert [group.child(i, 0).text() for i in range(2)] == ["Медленный", "Быстрый"]


def test_collapsed_group_stays_collapsed_after_refresh(made):
    app, _service = made
    _add_profile(app)
    app.activate()
    index = app.window.model.index(0, 0)

    app.window.tree.collapse(index)
    app.window.refresh_pages()

    assert not app.window.tree.isExpanded(app.window.model.index(0, 0))


def test_selected_profile_survives_refresh(made):
    app, _service = made
    entry = _add_profile(app)
    app.activate()
    app.window.tree.setCurrentIndex(app.window.model.profile_index(entry.id))

    app.window.refresh_pages()

    assert app.window.selected_profile_id() == entry.id


def test_close_with_tray_hides_the_window(made):
    app, _service = made
    app.tray_item = FakeTrayItem()
    app.start_tray()
    app.activate()

    app.window.close()

    assert app.window.isHidden()
    assert app.context.config.window_size
    app.stop_tray()


def test_close_without_tray_quits(made, monkeypatch):
    app, _service = made
    app.activate()
    quits = []
    monkeypatch.setattr(app, "quit", lambda: quits.append(1))

    app.window.close()

    assert quits == [1]


def test_notifications_go_to_the_tray(made):
    app, _service = made
    item = FakeTrayItem()
    app.tray_item = item
    app.start_tray()

    app.controller.notify_user("Переключаюсь на запасной")

    assert item.messages == [("Veblock", "Переключаюсь на запасной")]
    app.stop_tray()


def test_tray_menu_comes_from_the_shared_model(made):
    app, _service = made
    item = FakeTrayItem()
    app.tray_item = item
    _add_profile(app)

    app.start_tray()

    assert item.menu[-1].label == "Выход"
    app.stop_tray()


def test_shutdown_stops_the_core(made):
    app, service = made
    app.activate()

    app.shutdown()

    assert ("shutdown",) in service.calls


def test_qt_frontend_imports_without_gtk():
    """На Windows GTK нет: Qt-интерфейс и контроллер не должны тянуть gi."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['gi'] = None; "
        "import src.ui.qt.application, src.ui.qt.tray, src.ui.tray.controller"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_window_uses_the_bundled_style(made):
    app, _service = made

    app.activate()

    assert "#statusCard" in app.window.styleSheet()
