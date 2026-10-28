"""Формы Qt: профиль, группа, подписка."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from src.fmt import parse_link
from src.ui.qt.dialogs.group import GroupDialog
from src.ui.qt.dialogs.profile import AddProfileDialog, EditProfileDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog

pytestmark = pytest.mark.qt

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#FromLink"
OTHER = "vless://22222222-2222-2222-2222-222222222222@new.example:8443?type=tcp#New"


# --- добавление профиля ---


def test_add_profile_starts_disabled_and_accepts_a_link(qapp):
    dialog = AddProfileDialog()
    assert not dialog.confirm_button.isEnabled()

    dialog.link_edit.setText(f"  {LINK}  ")

    assert dialog.confirm_button.isEnabled()
    assert dialog.status.text().startswith("VLESS: host.example")
    assert dialog.name_edit.text() == "FromLink"


def test_add_profile_explains_a_broken_link(qapp):
    dialog = AddProfileDialog()

    dialog.link_edit.setText("vless://")

    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.text() == "Не удалось разобрать ссылку"
    assert dialog.status.property("error") is True


def test_add_profile_keeps_a_typed_name(qapp):
    dialog = AddProfileDialog()
    dialog.name_edit.setText("Мой")
    dialog.name_edit.textEdited.emit("Мой")

    dialog.link_edit.setText(LINK)

    assert dialog.name_edit.text() == "Мой"
    assert dialog.get_profile().name == "Мой"


def test_add_profile_reports_the_bean_and_closes(qapp):
    dialog = AddProfileDialog(link=LINK)
    seen = []
    dialog.profile_ready.connect(seen.append)

    dialog.confirm_button.click()

    assert [bean.name for bean in seen] == ["FromLink"]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_paste_takes_the_clipboard(qapp):
    QApplication.clipboard().setText(f"{LINK}\n")
    dialog = AddProfileDialog()

    dialog.paste_button.click()

    assert dialog.link_edit.text() == LINK


# --- правка профиля ---


def _profile():
    return SimpleNamespace(id=1, bean=parse_link(LINK))


def test_edit_profile_is_prefilled(qapp):
    dialog = EditProfileDialog(_profile())

    assert dialog.name_edit.text() == "FromLink"
    assert dialog.address_edit.text() == "host.example"
    assert dialog.port_spin.value() == 443
    assert dialog.link_edit.text().startswith("vless://")


def test_applied_link_waits_for_save(qapp):
    profile = _profile()
    dialog = EditProfileDialog(profile)
    dialog.link_edit.setText(OTHER)

    assert dialog.apply_link()
    assert profile.bean.server_address == "host.example"
    assert dialog.address_edit.text() == "new.example"

    dialog.confirm_button.click()
    assert profile.bean.server_address == "new.example"
    assert profile.bean.server_port == 8443


def test_broken_link_changes_nothing(qapp):
    dialog = EditProfileDialog(_profile())
    dialog.link_edit.setText("garbage")

    assert not dialog.apply_link()
    assert dialog.status.property("error") is True
    assert dialog.address_edit.text() == "host.example"


def test_empty_address_keeps_the_old_one(qapp):
    profile = _profile()
    dialog = EditProfileDialog(profile)
    saved = []
    dialog.profile_saved.connect(lambda: saved.append(1))
    dialog.address_edit.setText(" ")
    dialog.name_edit.setText(" Новое ")

    dialog.confirm_button.click()

    assert saved == [1]
    assert profile.bean.server_address == "host.example"
    assert profile.bean.name == "Новое"


def test_copy_puts_the_link_on_the_clipboard(qapp):
    dialog = EditProfileDialog(_profile())

    dialog.copy_button.click()

    assert QApplication.clipboard().text() == dialog.link_edit.text()
    assert dialog.status.text() == "Ссылка скопирована"


# --- группа ---


def test_group_dialog_titles_and_saving(qapp):
    assert GroupDialog().windowTitle() == "Новая группа"
    plain = SimpleNamespace(name="Дом", is_subscription=False)
    assert GroupDialog(plain).windowTitle() == "Редактировать группу"

    dialog = GroupDialog()
    assert not dialog.confirm_button.isEnabled()
    dialog.name_edit.setText("  Работа ")
    seen = []
    dialog.group_ready.connect(seen.append)
    dialog.confirm_button.click()

    assert seen == ["Работа"]


# --- подписка ---


def _group(**kwargs):
    return SimpleNamespace(
        id=1,
        name=kwargs.get("name", "Sub"),
        subscription_url=kwargs.get("url", "https://e.com/s"),
        last_updated=kwargs.get("last_updated", 0),
    )


def test_new_subscription_is_empty_and_quiet(qapp):
    dialog = SubscriptionDialog()

    assert dialog.windowTitle() == "Добавить подписку"
    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.isHidden()
    assert dialog.form.rowCount() == 2  # «Обновлено» только у существующей


def test_bad_url_is_explained(qapp):
    dialog = SubscriptionDialog()

    dialog.url_edit.setText("ftp://e.com")

    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.text() == "URL должен начинаться с http:// или https://"


def test_missing_name_falls_back_to_the_host(qapp):
    dialog = SubscriptionDialog()
    seen = []
    dialog.subscription_ready.connect(lambda name, url: seen.append((name, url)))

    dialog.url_edit.setText(" https://sub.example.org/x ")
    dialog.confirm_button.click()

    assert seen and seen[0][1] == "https://sub.example.org/x"
    assert seen[0][0]


def test_existing_subscription_is_prefilled(qapp):
    dialog = SubscriptionDialog(_group(name="Провайдер"))

    assert dialog.windowTitle() == "Редактировать подписку"
    assert dialog.name_edit.text() == "Провайдер"
    assert dialog.url_edit.text() == "https://e.com/s"
    assert dialog.updated_label.text() == "Никогда"
