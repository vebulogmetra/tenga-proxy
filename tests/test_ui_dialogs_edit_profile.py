"""Widget tests for the GTK4 edit-profile dialog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gtk

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Old"
OTHER = "vless://22222222-2222-2222-2222-222222222222@new.example:8443?type=tcp#New"


def make_profile():
    from src.fmt import parse_link

    return SimpleNamespace(id=1, bean=parse_link(LINK))


def make_dialog(profile):
    from src.ui.dialogs4.edit_profile import EditProfileDialog

    return EditProfileDialog(profile)


def test_the_fields_are_prefilled_from_the_bean(gtk_ready):
    dialog = make_dialog(make_profile())
    assert dialog.name_row.get_text() == "Old"
    assert dialog.address_row.get_text() == "host.example"
    assert dialog.port_row.get_value() == 443


def test_the_share_link_is_shown(gtk_ready):
    assert "vless://" in make_dialog(make_profile()).link_row.get_text()


def test_applying_a_new_link_refreshes_the_fields(gtk_ready):
    dialog = make_dialog(make_profile())
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    assert dialog.name_row.get_text() == "New"
    assert dialog.address_row.get_text() == "new.example"
    assert dialog.port_row.get_value() == 8443


def test_a_broken_link_is_rejected_and_changes_nothing(gtk_ready):
    dialog = make_dialog(make_profile())
    dialog.link_row.set_text("garbage")
    dialog.apply_link()
    assert dialog.name_row.get_text() == "Old"
    assert "разобрать" in dialog.status_label.get_text()


def test_a_pending_bean_is_not_written_before_saving(gtk_ready):
    """Диалог правит живой объект хранилища — Отмена должна ничего не менять."""
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    assert profile.bean.server_address == "host.example"


def test_saving_applies_the_pending_bean(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    dialog.apply_changes()
    assert profile.bean.server_address == "new.example"
    assert profile.bean.server_port == 8443


def test_saving_applies_the_typed_fields(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.name_row.set_text("Renamed")
    dialog.address_row.set_text("other.example")
    dialog.port_row.set_value(9443)
    dialog.apply_changes()
    assert profile.bean.name == "Renamed"
    assert profile.bean.server_address == "other.example"
    assert profile.bean.server_port == 9443


def test_an_empty_address_is_ignored_on_save(gtk_ready):
    """Пустой адрес сделал бы профиль неработоспособным без предупреждения."""
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.address_row.set_text("")
    dialog.apply_changes()
    assert profile.bean.server_address == "host.example"


def test_a_typed_field_wins_over_the_applied_link(gtk_ready):
    """Ссылка применяется первой, поля — поверх неё: правка руками важнее."""
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    dialog.name_row.set_text("Manual")
    dialog.apply_changes()
    assert profile.bean.name == "Manual"
    assert profile.bean.server_address == "new.example"


def test_applying_a_link_twice_keeps_the_last_one(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    dialog.link_row.set_text(LINK)
    dialog.apply_link()
    dialog.apply_changes()
    assert profile.bean.server_address == "host.example"
