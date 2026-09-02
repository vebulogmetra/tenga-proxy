"""Widget tests for the GTK4 add-profile dialog."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#FromLink"


@pytest.fixture
def dialog(gtk_ready):
    from src.ui.dialogs.add_profile import AddProfileDialog

    return AddProfileDialog()


def test_a_valid_link_enables_the_add_button(dialog):
    dialog.link_row.set_text(LINK)
    assert dialog.add_button.get_sensitive()


def test_an_invalid_link_disables_it(dialog):
    dialog.link_row.set_text("garbage")
    assert not dialog.add_button.get_sensitive()


def test_the_button_starts_disabled(dialog):
    assert not dialog.add_button.get_sensitive()


def test_an_empty_link_leaves_the_hint_blank(dialog):
    """Пустое поле — не ошибка: диалог только что открыли."""
    dialog.link_row.set_text(LINK)
    dialog.link_row.set_text("")
    assert dialog.status_label.get_text() == ""


def test_the_hint_names_the_parsed_protocol(dialog):
    dialog.link_row.set_text(LINK)
    assert "VLESS" in dialog.status_label.get_text()


def test_a_broken_link_is_explained(dialog):
    dialog.link_row.set_text("garbage")
    assert "разобрать" in dialog.status_label.get_text()


def test_the_name_is_prefilled_from_the_link(dialog):
    dialog.link_row.set_text(LINK)
    assert dialog.name_row.get_text() == "FromLink"


def test_a_typed_name_is_not_overwritten(dialog):
    dialog.name_row.set_text("Mine")
    dialog.link_row.set_text(LINK)
    assert dialog.name_row.get_text() == "Mine"


def test_get_profile_returns_the_bean(dialog):
    dialog.link_row.set_text(LINK)
    bean = dialog.get_profile()
    assert bean is not None
    assert bean.name == "FromLink"


def test_a_custom_name_reaches_the_bean(dialog):
    dialog.name_row.set_text("Mine")
    dialog.link_row.set_text(LINK)
    assert dialog.get_profile().name == "Mine"


def test_get_profile_is_none_without_a_link(dialog):
    assert dialog.get_profile() is None


def test_a_link_with_surrounding_space_is_accepted(dialog):
    """Из буфера ссылка обычно приходит с переводом строки."""
    dialog.link_row.set_text(f"  {LINK}\n")
    assert dialog.add_button.get_sensitive()
