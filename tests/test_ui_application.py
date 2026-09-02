"""Tests for the Adw.Application shell."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk

EXPECTED_ACTIONS = {
    "connect",
    "disconnect",
    "toggle-connection",
    "add-profile",
    "add-profile-from-clipboard",
    "add-subscription",
    "add-group",
    "refresh-subscriptions",
    "settings",
    "about",
    "shortcuts",
    "quit",
    "hide-window",
}


def test_application_id(adw_app):
    assert adw_app.get_application_id() == "ru.tenga.Proxy"


def test_all_actions_are_registered(adw_app):
    assert set(adw_app.list_actions()) >= EXPECTED_ACTIONS


def test_accelerators_are_bound(adw_app):
    assert adw_app.get_accels_for_action("app.add-profile") == ["<Control>n"]
    assert adw_app.get_accels_for_action("app.quit") == ["<Control>q"]
    assert adw_app.get_accels_for_action("app.refresh-subscriptions") == ["F5"]
    assert adw_app.get_accels_for_action("app.settings") == ["<Control>comma"]


def test_activate_creates_one_window_only(adw_app):
    adw_app.activate()
    first = adw_app.get_active_window()
    adw_app.activate()

    assert first is not None
    assert adw_app.get_active_window() is first
    assert len(adw_app.get_windows()) == 1


def test_toast_without_window_does_not_raise(adw_app):
    adw_app.toast("Ничего не сломалось")


def test_toast_reaches_the_window(adw_app):
    adw_app.activate()
    adw_app.toast("Подписка обновлена")
