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


def test_latency_probe_is_called_for_every_profile(adw_app):
    """The test-latency action probes each profile and stores the result."""
    adw_app.activate()
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )

    probed: list[int] = []

    def fake_probe(profile_id: int) -> int:
        probed.append(profile_id)
        return 55

    adw_app.set_latency_probe(fake_probe)
    adw_app.activate_action("test-latency", None)
    adw_app.wait_for_latency_for_test()

    assert probed == [entry.id]
    assert store.get_profile(entry.id).latency_ms == 55


def test_latency_probe_failure_does_not_crash(adw_app):
    adw_app.activate()
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    entry = store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )

    def failing_probe(_profile_id: int) -> int:
        raise RuntimeError("нет бинарника")

    adw_app.set_latency_probe(failing_probe)
    adw_app.activate_action("test-latency", None)
    adw_app.wait_for_latency_for_test()

    assert store.get_profile(entry.id).latency_ms == -1


def test_second_latency_run_is_ignored_while_busy(adw_app):
    """Two concurrent runs would interleave writes into the same profiles."""
    import threading

    adw_app.activate()
    store = adw_app.context.profiles
    group = store.add_group("Тест")
    store.parse_and_add_link(
        "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба",
        group_id=group.id,
    )

    release = threading.Event()
    calls: list[int] = []

    def slow_probe(profile_id: int) -> int:
        calls.append(profile_id)
        release.wait(timeout=5)
        return 10

    adw_app.set_latency_probe(slow_probe)
    adw_app.activate_action("test-latency", None)
    adw_app.activate_action("test-latency", None)
    release.set()
    adw_app.wait_for_latency_for_test()

    assert len(calls) == 1


def test_refresh_subscriptions_reports_the_result(adw_app):
    adw_app.activate()
    store = adw_app.context.profiles
    group = store.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/list"

    updated: list[int] = []

    def fake_update(group_id: int, url: str) -> int:
        updated.append(group_id)
        return 3

    adw_app.set_subscription_updater(fake_update)
    adw_app.activate_action("refresh-subscriptions", None)
    adw_app.wait_for_subscriptions_for_test()

    assert updated == [group.id]


def test_refresh_without_subscriptions_is_a_no_op(adw_app):
    adw_app.activate()

    called: list[int] = []
    adw_app.set_subscription_updater(lambda gid, _url: called.append(gid) or 0)
    adw_app.activate_action("refresh-subscriptions", None)
    adw_app.wait_for_subscriptions_for_test()

    assert called == []
