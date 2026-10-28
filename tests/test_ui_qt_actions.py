"""Действия Qt-приложения открывают формы и передают результат контроллеру."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.logic.routing_import import ImportRow
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.about import AboutDialog
from src.ui.qt.dialogs.group import GroupDialog
from src.ui.qt.dialogs.profile import AddProfileDialog, EditProfileDialog
from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog
from src.ui.qt.dialogs.routing_import import RoutingImportDialog
from src.ui.qt.dialogs.shortcuts import ShortcutsDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog
from tests.support.qt import process_events

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    app.activate()
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()
    app.window.detach()
    app.window.deleteLater()
    process_events()


def _profile(app, name="Проба", group_id=None):
    return app.controller.add_profile_from_bean(
        parse_link(LINK.replace("Проба", name)), group_id=group_id
    )


def _click(box: QMessageBox, text: str) -> None:
    next(b for b in box.buttons() if b.text() == text).click()
    process_events()


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        ("add-profile", AddProfileDialog),
        ("add-subscription", SubscriptionDialog),
        ("add-group", GroupDialog),
        ("about", AboutDialog),
        ("shortcuts", ShortcutsDialog),
    ],
)
def test_actions_open_their_dialogs(app, action, kind):
    app.actions[action].trigger()

    assert isinstance(app.current_dialog, kind)
    assert app.current_dialog.parent() is app.window


def test_added_profile_reaches_the_store(app):
    app.actions["add-profile"].trigger()
    dialog = app.current_dialog
    dialog.link_edit.setText(LINK)

    dialog.confirm_button.click()
    process_events()

    assert [p.name for p in app.context.profiles.profiles.values()] == ["Проба"]
    assert app.last_toast_for_test == "Профиль добавлен: Проба"
    assert app.current_dialog is None


def test_clipboard_action_prefills_the_link(app):
    QApplication.clipboard().setText(LINK)

    app.actions["add-profile-from-clipboard"].trigger()

    assert app.current_dialog.link_edit.text() == LINK
    assert app.current_dialog.confirm_button.isEnabled()


def test_subscription_link_opens_a_prefilled_form(app, monkeypatch):
    seen = []
    monkeypatch.setattr(app.controller, "add_subscription", lambda n, u: seen.append((n, u)))

    app.controller._shell.open_subscription_form("Провайдер", "https://sub.example.org/s")
    dialog = app.current_dialog
    assert isinstance(dialog, SubscriptionDialog)
    assert dialog.name_edit.text() == "Провайдер"
    dialog.confirm_button.click()

    assert seen == [("Провайдер", "https://sub.example.org/s")]


def test_routing_import_is_a_dialog(app):
    confirmed = []

    app.controller._shell.open_routing_import(
        [ImportRow("Режим", "a → b")], lambda: confirmed.append(1)
    )

    dialog = app.current_dialog
    assert isinstance(dialog, RoutingImportDialog)
    dialog.import_button.click()
    assert confirmed == [1]


def test_edit_profile_saves_through_the_controller(app):
    entry = _profile(app)

    app.activate_action("edit-profile", entry.id)
    dialog = app.current_dialog
    assert isinstance(dialog, EditProfileDialog)
    dialog.name_edit.setText("Другое")
    dialog.confirm_button.click()
    process_events()

    assert app.context.profiles.get_profile(entry.id).name == "Другое"
    group = app.window.model.item(0, 0)
    assert group.child(0, 0).text() == "Другое"


def test_delete_profile_asks_first(app):
    entry = _profile(app)

    app.activate_action("delete-profile", entry.id)
    box = app.current_dialog
    assert box.text() == "«Проба» будет удалён безвозвратно."
    _click(box, "Удалить")

    assert app.context.profiles.get_profile(entry.id) is None


def test_missing_profile_is_reported(app):
    app.activate_action("edit-profile", 999)

    assert app.current_dialog is None
    assert app.last_toast_for_test == "Профиль не найден"


def test_profile_routing_opens(app):
    entry = _profile(app)

    app.activate_action("profile-routing", entry.id)

    assert isinstance(app.current_dialog, ProfileRoutingDialog)


def test_edit_group_picks_the_form_by_kind(app):
    plain = app.controller.add_group("Дом")
    subscription = app.context.profiles.add_group("Подписка", is_subscription=True)

    app.activate_action("edit-group", plain.id)
    assert isinstance(app.current_dialog, GroupDialog)
    app.current_dialog.name_edit.setText("Работа")
    app.current_dialog.confirm_button.click()
    process_events()
    assert app.context.profiles.get_group(plain.id).name == "Работа"

    app.activate_action("edit-group", subscription.id)
    assert isinstance(app.current_dialog, SubscriptionDialog)


def test_delete_group_counts_its_profiles(app):
    group = app.controller.add_group("Дом")
    _profile(app, group_id=group.id)

    app.activate_action("delete-group", group.id)

    assert app.current_dialog.text() == "«Дом» и 1 профилей внутри будут удалены безвозвратно."
    _click(app.current_dialog, "Удалить")
    assert app.context.profiles.get_group(group.id) is None


def test_row_actions_reach_the_controller(app, monkeypatch):
    seen = []
    monkeypatch.setattr(app.controller, "test_latency_for", lambda pid: seen.append(("p", pid)))
    monkeypatch.setattr(
        app.controller, "test_latency_for_group", lambda gid: seen.append(("g", gid))
    )

    app.activate_action("test-profile", 5)
    app.activate_action("test-group", "7")

    assert seen == [("p", 5), ("g", 7)]


def test_provider_links_are_checked_before_opening(app, monkeypatch):
    opened = []
    monkeypatch.setattr("src.ui.qt.application.open_url", opened.append)
    group = app.context.profiles.add_group("Подписка", is_subscription=True)
    group.sub_web_page_url = "javascript:alert(1)"

    app.activate_action("open-subscription-page", group.id)
    assert opened == []
    assert app.last_toast_for_test == "Ссылка недоступна"

    group.sub_support_url = "https://t.me/provider"
    app.activate_action("open-subscription-support", group.id)
    assert opened == ["https://t.me/provider"]


def test_a_second_dialog_waits_for_the_first(app):
    app.actions["about"].trigger()

    app.actions["add-profile"].trigger()

    assert isinstance(app.current_dialog, AboutDialog)
