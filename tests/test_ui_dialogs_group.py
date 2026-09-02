"""Widget tests for the GTK4 group dialog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gtk


def make_dialog(group=None):
    from src.ui.dialogs.group import GroupDialog

    return GroupDialog(group=group)


def test_a_new_group_starts_empty(gtk_ready):
    assert make_dialog().name_row.get_text() == ""


def test_an_existing_group_is_prefilled(gtk_ready):
    group = SimpleNamespace(id=1, name="Home", is_subscription=False)
    assert make_dialog(group).name_row.get_text() == "Home"


def test_a_name_enables_saving(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("Home")
    assert dialog.save_button.get_sensitive()


def test_a_blank_name_blocks_saving(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("   ")
    assert not dialog.save_button.get_sensitive()


def test_the_button_starts_disabled_for_a_new_group(gtk_ready):
    assert not make_dialog().save_button.get_sensitive()


def test_get_name_is_trimmed(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("  Home  ")
    assert dialog.get_name() == "Home"


def test_get_name_is_none_when_blank(gtk_ready):
    assert make_dialog().get_name() is None


def test_the_title_names_a_subscription(gtk_ready):
    """Подписка редактируется тем же диалогом — заголовок должен это отражать."""
    group = SimpleNamespace(id=1, name="Sub", is_subscription=True)
    assert make_dialog(group).get_title() == "Редактировать подписку"


def test_the_title_names_a_plain_group(gtk_ready):
    group = SimpleNamespace(id=1, name="Home", is_subscription=False)
    assert make_dialog(group).get_title() == "Редактировать группу"


def test_the_title_of_a_new_group(gtk_ready):
    assert make_dialog().get_title() == "Новая группа"
