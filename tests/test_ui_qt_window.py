"""Главное окно Qt: меню строк, «Добавить», подписки, настройки окна, журнал."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.profile import AddProfileDialog
from src.ui.qt.models import ADDRESS_COLUMN, EXPIRED_COLOR, NAME_COLUMN
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
    window.monitoring_button.setChecked(False)

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
    cell = made.window.model.item(row, NAME_COLUMN)
    assert made.window.model.item(row, ADDRESS_COLUMN).text() == ""
    assert made.window.tree.isFirstColumnSpanned(row, cell.index().parent())

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
    assert window.monitoring_body.isHidden()

    window.monitoring_button.setChecked(True)
    window.save_geometry()

    assert made.context.config.monitoring_panel is True
    assert window.monitoring_body.isVisible()


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
    assert not panel.active
    made.window.show_diagnostics()
    assert panel.active

    made.window.monitoring_button.setChecked(False)
    assert panel.active
    made.window.diagnostics_window.close()
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


@pytest.mark.parametrize("size", [(900, 600), (1180, 760), (1920, 1080)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_layout_keeps_the_primary_action_compact(made, size, theme):
    from src.ui.qt.theme import apply_theme

    apply_theme(theme)
    group = made.context.profiles.add_group("Тестовая подписка", is_subscription=True)
    group.sub_user_info = "upload=0; download=1073741824; total=2147483648"
    for number in range(12):
        _profile(made, f"🇩🇪 Берлин — тестовый сервер {number}", group_id=group.id)
    made.activate()
    window = made.window
    window.monitoring_button.setChecked(False)
    profile = next(iter(made.context.profiles.profiles.values()))
    window.tree.setCurrentIndex(window.model.profile_index(profile.id))
    window.showNormal()
    window.resize(*size)
    process_events()
    card = window.status_card
    assert not hasattr(card, "button")
    assert card.title.width() >= card.title.fontMetrics().horizontalAdvance(card.title.text())
    assert card.logo.geometry().right() < card.width()
    assert not window.empty_label.isVisible()

    # Optional local visual evidence, using synthetic profiles only.
    import os
    from pathlib import Path

    if output := os.environ.get("VEBLOCK_QT_SCREENSHOTS"):
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(path / f"main-{theme}-{size[0]}.png"))


def test_empty_search_has_an_explanation(made):
    _profile(made)
    made.activate()
    made.window.search.setText("несуществующий сервер")
    assert made.window.empty_label.isVisible()
    assert "Ничего не найдено" in made.window.empty_label.text()
    made.window.search.clear()
    assert not made.window.empty_label.isVisible()


def test_journal_wrap_is_optional(made):
    from PySide6.QtWidgets import QPlainTextEdit

    made.activate()
    panel = made.window.diagnostics
    assert panel.view.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    panel.wrap_button.setChecked(True)
    assert panel.view.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth


def test_journal_refresh_preserves_reading_position(made, tmp_path, monkeypatch):
    panel, _logs = _diagnostics(made, tmp_path)
    made.window.show_diagnostics()
    wait_until(lambda: not panel._busy)
    panel.set_active(False)
    panel.view.setPlainText("\n".join(f"Строка {i}" for i in range(200)))
    bar = panel.view.verticalScrollBar()
    bar.setValue(40)
    position = bar.value()

    def run(fn, on_done=None, on_error=None, *, name):
        on_done("\n".join(f"Строка {i}" for i in range(220)))

    monkeypatch.setattr(panel, "_run", run)
    panel.refresh()
    assert bar.value() == position
    bar.setValue(bar.maximum())
    panel.refresh()
    assert bar.value() == bar.maximum()
