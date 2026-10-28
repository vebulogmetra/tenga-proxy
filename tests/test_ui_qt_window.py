"""Главное окно Qt: меню строк, «Добавить», подписки, настройки окна, журнал."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.profile import AddProfileDialog
from src.ui.qt.models import ADDRESS_COLUMN, EXPIRED_COLOR
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


class TrayItem:
    """Трей без системы: только интерфейс элемента."""

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


@pytest.fixture
def made(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()
    app.stop_tray()
    if app.window is not None:
        app.window.detach()
        app.window.deleteLater()
    process_events()


def _profile(app, name="Проба", group_id=None):
    return app.controller.add_profile_from_bean(
        parse_link(LINK.replace("Проба", name)), group_id=group_id
    )


def _labels(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# --- меню строк ---


def test_profile_menu_matches_gtk(made):
    entry = _profile(made)
    made.activate()

    menu = made.window.context_menu(made.window.model.profile_index(entry.id))

    assert _labels(menu) == [
        "Подключить",
        "VPN и маршруты…",
        "Тест задержки",
        "Редактировать",
        "Удалить",
    ]


def test_group_menu_and_subscription_extra(made):
    plain = made.controller.add_group("Дом")
    _profile(made, group_id=plain.id)
    subscription = made.context.profiles.add_group("Провайдер", is_subscription=True)
    _profile(made, group_id=subscription.id)
    made.activate()
    window = made.window

    plain_menu = window.context_menu(window.model.group_index(plain.id))
    sub_menu = window.context_menu(window.model.group_index(subscription.id))

    assert _labels(plain_menu) == [
        "Свернуть группу",
        "Тест задержки",
        "Оставить рабочие…",
        "Редактировать",
        "Удалить",
    ]
    assert "Обновить подписку" in _labels(sub_menu)


def test_menu_entry_runs_the_row_action(made):
    entry = _profile(made)
    made.activate()

    menu = made.window.context_menu(made.window.model.profile_index(entry.id))
    next(a for a in menu.actions() if a.text() == "Удалить").trigger()

    assert isinstance(made.current_dialog, QMessageBox)


def test_toggle_group_flips_the_branch(made):
    group = made.controller.add_group("Дом")
    _profile(made, group_id=group.id)
    made.activate()
    index = made.window.model.group_index(group.id)
    assert made.window.tree.isExpanded(index)

    made.activate_action("toggle-group", group.id)

    assert not made.window.tree.isExpanded(made.window.model.group_index(group.id))
    menu = made.window.context_menu(made.window.model.group_index(group.id))
    assert _labels(menu)[0] == "Развернуть группу"


# --- низ окна и дерево ---


def test_add_menu_runs_the_actions(made):
    made.activate()

    assert _labels(made.window.add_menu) == [
        "Профиль по ссылке…",
        "Профиль из буфера обмена",
        "Подписка…",
        "Группа…",
    ]
    made.window.add_menu.actions()[0].trigger()
    assert isinstance(made.current_dialog, AddProfileDialog)


def test_subscription_details_are_in_the_group_row(made):
    group = made.context.profiles.add_group("Провайдер", is_subscription=True)
    group.sub_user_info = "upload=0; download=1073741824; total=2147483648; expire=1000000000"
    _profile(made, group_id=group.id)
    made.activate()

    row = made.window.model.group_index(group.id).row()
    cell = made.window.model.item(row, ADDRESS_COLUMN)

    assert " из " in cell.text()
    assert "истекла" in cell.text()
    assert cell.foreground().color() == EXPIRED_COLOR


def test_status_card_shows_the_flag_as_a_picture(made):
    entry = _profile(made, "🇩🇪 Берлин")
    made.activate()

    made.context.proxy_state.set_running(entry.id, mode="system")
    made.window.refresh_status()

    card = made.window.status_card
    assert card.subtitle.text() == "Берлин"
    assert not card.flag.isHidden()
    assert card.subtitle.toolTip() == "🇩🇪 Берлин"


# --- настройки окна ---


def test_close_to_tray_can_be_turned_off(made, monkeypatch):
    made.tray_item = TrayItem()
    made.start_tray()
    made.context.config.close_to_tray = False
    made.activate()
    quits = []
    monkeypatch.setattr(made, "quit", lambda: quits.append(1))

    made.window.close()

    assert quits == [1]


def test_monitoring_panel_visibility_is_remembered(made, qapp):
    made.context.config.monitoring_panel = False
    made.activate()
    window = made.window
    assert not window.monitoring_button.isChecked()
    assert window.monitoring_dock.isHidden()

    window.monitoring_button.setChecked(True)
    window.save_geometry()

    assert made.context.config.monitoring_panel is True
    assert not window.monitoring_dock.isHidden()


# --- журнал ---


def _diagnostics(made, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "tenga_gui.log").write_text("строка журнала\n", encoding="utf-8")
    made.activate()
    panel = made.window.diagnostics
    panel._log_dir = lambda: logs
    return panel, logs


def test_journal_is_read_in_the_background(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)

    panel.refresh()

    wait_until(lambda: "строка журнала" in panel.view.toPlainText())


def test_journal_reads_only_while_visible(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)
    assert panel.active

    made.window.monitoring_button.setChecked(False)
    assert not panel.active


def test_export_writes_the_cleaned_journal(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)
    target = tmp_path / "export.txt"
    panel.ask_export_path = lambda _parent: str(target)

    panel.export()
    panel.thread.join(5)

    assert "строка журнала" in target.read_text(encoding="utf-8")


def test_clear_asks_and_removes_the_files(made, tmp_path):
    panel, logs = _diagnostics(made, tmp_path)

    panel.clear()
    box = made.current_dialog
    assert isinstance(box, QMessageBox)
    next(b for b in box.buttons() if b.text() == "Очистить").click()

    # Открытые журналы обрезаются, а не удаляются: в них пишут обработчики.
    wait_until(lambda: (logs / "tenga_gui.log").read_text(encoding="utf-8") == "")
