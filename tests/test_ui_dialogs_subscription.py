"""Widget tests for the GTK4 subscription dialog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gtk


def make_dialog(group=None):
    from src.ui.dialogs.subscription import SubscriptionDialog

    return SubscriptionDialog(group=group)


def group(**kwargs):
    return SimpleNamespace(
        id=kwargs.get("id", 1),
        name=kwargs.get("name", "Sub"),
        subscription_url=kwargs.get("url", "https://e.com/s"),
        last_updated=kwargs.get("last_updated", 0),
    )


def test_the_new_dialog_starts_empty(gtk_ready):
    dialog = make_dialog()
    assert dialog.name_row.get_text() == ""
    assert dialog.url_row.get_text() == ""


def test_an_existing_group_prefills_the_fields(gtk_ready):
    dialog = make_dialog(group())
    assert dialog.name_row.get_text() == "Sub"
    assert dialog.url_row.get_text() == "https://e.com/s"


def test_a_valid_url_enables_saving(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("Sub")
    dialog.url_row.set_text("https://e.com/s")
    assert dialog.save_button.get_sensitive()


def test_a_non_http_url_blocks_saving(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("Sub")
    dialog.url_row.set_text("ftp://e.com")
    assert not dialog.save_button.get_sensitive()


def test_a_missing_name_blocks_saving(gtk_ready):
    dialog = make_dialog()
    dialog.url_row.set_text("https://e.com/s")
    assert not dialog.save_button.get_sensitive()


def test_the_hint_explains_a_bad_url(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("Sub")
    dialog.url_row.set_text("ftp://e.com")
    assert "http" in dialog.status_label.get_text().lower()


def test_get_data_returns_the_trimmed_pair(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("  Sub  ")
    dialog.url_row.set_text("  https://e.com/s  ")
    assert dialog.get_data() == ("Sub", "https://e.com/s")


def test_get_data_is_none_when_invalid(gtk_ready):
    dialog = make_dialog()
    dialog.name_row.set_text("Sub")
    assert dialog.get_data() is None


def test_the_last_update_is_shown_when_known(gtk_ready):
    dialog = make_dialog(group(last_updated=1_700_000_000))
    assert "2023" in dialog.updated_row.get_subtitle()


def test_a_never_updated_subscription_says_so(gtk_ready):
    assert make_dialog(group()).updated_row.get_subtitle() == "Никогда"


def test_a_new_subscription_hides_the_update_row(gtk_ready):
    """Для ещё не созданной подписки строка «Обновлено» бессмысленна."""
    assert not make_dialog().updated_row.get_visible()


def test_the_title_differs_for_a_new_subscription(gtk_ready):
    assert make_dialog().get_title() == "Добавить подписку"


def test_the_title_differs_for_an_existing_one(gtk_ready):
    assert make_dialog(group()).get_title() == "Редактировать подписку"
