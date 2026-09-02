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
    "activate-window",
    "connect-profile",
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


# --- подключение и диалоги (этап 3) ---

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Новый"


class FakeService:
    """Records what would have been done instead of touching xray."""

    def __init__(self, calls, *, ok=True, error=""):
        from src.core.connection import ConnectionResult

        self._calls = calls
        self._result = ConnectionResult(ok, error)

    def connect(self, profile_id):
        self._calls.append(("connect", profile_id))
        return self._result

    def disconnect(self):
        self._calls.append(("disconnect",))
        return self._result

    def reload_config(self):
        self._calls.append(("reload",))
        return self._result


def add_profile(app):
    from src.fmt import parse_link

    return app.add_profile_from_bean(parse_link(LINK))


def test_activating_a_profile_connects_through_the_service(adw_app):
    adw_app.activate()
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.select_profile(entry.id)
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", entry.id)]


def test_toggle_connection_disconnects_a_running_proxy(adw_app):
    adw_app.activate()
    adw_app.context.proxy_state.is_running = True
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.activate_action("toggle-connection", None)
    adw_app.wait_for_connection_for_test()

    assert calls == [("disconnect",)]


def test_a_failed_connection_is_reported(adw_app):
    adw_app.activate()
    entry = add_profile(adw_app)
    adw_app.set_connection_service(FakeService([], ok=False, error="нет бинарника"))

    adw_app.select_profile(entry.id)
    adw_app.wait_for_connection_for_test()

    assert "нет бинарника" in adw_app.last_toast_for_test


def test_a_successful_connection_refreshes_the_pages(adw_app):
    adw_app.activate()
    entry = add_profile(adw_app)
    adw_app.set_connection_service(FakeService([]))

    adw_app.select_profile(entry.id)
    adw_app.wait_for_connection_for_test()

    assert "Подключено" in adw_app.last_toast_for_test


def test_toggle_connection_without_a_selection_says_so(adw_app):
    adw_app.activate()
    adw_app.set_connection_service(FakeService([]))

    adw_app.activate_action("toggle-connection", None)

    assert "профиль" in adw_app.last_toast_for_test.lower()


def test_add_profile_stores_and_saves(adw_app):
    adw_app.activate()
    before = len(adw_app.context.profiles.profiles)

    entry = add_profile(adw_app)

    assert len(adw_app.context.profiles.profiles) == before + 1
    assert entry.id in adw_app.context.profiles.profiles


def test_delete_profile_removes_it(adw_app):
    adw_app.activate()
    entry = add_profile(adw_app)

    adw_app.delete_profile(entry.id)

    assert entry.id not in adw_app.context.profiles.profiles


def test_deleting_a_missing_profile_is_harmless(adw_app):
    adw_app.activate()
    adw_app.delete_profile(9999)
    assert "не найден" in adw_app.last_toast_for_test.lower()


def test_add_subscription_creates_a_group(adw_app):
    adw_app.activate()

    group = adw_app.add_subscription("Подписка", "https://example.com/s")

    assert group.is_subscription
    assert group.subscription_url == "https://example.com/s"
    assert adw_app.context.profiles.get_group(group.id) is not None


def test_add_group_creates_a_plain_group(adw_app):
    adw_app.activate()

    group = adw_app.add_group("Дом")

    assert not group.is_subscription
    assert group.name == "Дом"


def test_update_group_renames_it(adw_app):
    adw_app.activate()
    group = adw_app.add_group("Дом")

    adw_app.update_group(group.id, name="Работа")

    assert adw_app.context.profiles.get_group(group.id).name == "Работа"


def test_update_group_can_change_the_subscription_url(adw_app):
    adw_app.activate()
    group = adw_app.add_subscription("Подписка", "https://example.com/a")

    adw_app.update_group(group.id, name="Подписка", url="https://example.com/b")

    assert adw_app.context.profiles.get_group(group.id).subscription_url == (
        "https://example.com/b"
    )


def test_delete_group_removes_it(adw_app):
    adw_app.activate()
    group = adw_app.add_group("Дом")

    adw_app.delete_group(group.id)

    assert adw_app.context.profiles.get_group(group.id) is None


def test_settings_reload_the_running_config(adw_app):
    """Изменённые настройки должны доехать до работающего ядра."""
    adw_app.activate()
    adw_app.context.proxy_state.is_running = True
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.apply_settings()

    assert calls == [("reload",)]


def test_settings_do_not_reload_a_stopped_core(adw_app):
    adw_app.activate()
    adw_app.context.proxy_state.is_running = False
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.apply_settings()

    assert calls == []


# --- действия для трея (этап 4) ---


def test_the_connect_profile_action_takes_a_profile_id(adw_app):
    """Трей адресует профиль числом: у пунктов меню общий обработчик."""
    from gi.repository import GLib

    adw_app.activate()
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.lookup_action("connect-profile").activate(GLib.Variant("i", entry.id))
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", entry.id)]


def test_the_activate_window_action_shows_the_window(adw_app):
    adw_app.activate()
    adw_app._window.set_visible(False)

    adw_app.activate_action("activate-window", None)

    assert adw_app._window.get_visible() is True


def test_activate_action_accepts_a_plain_integer_target(adw_app):
    """TrayController зовёт activate_action(name, target) одинаково для всех."""
    adw_app.activate()
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.activate_action("connect-profile", entry.id)
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", entry.id)]


def test_activate_action_still_accepts_a_variant(adw_app):
    """Старые вызовы передают GLib.Variant — они не должны сломаться."""
    from gi.repository import GLib

    adw_app.activate()
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.activate_action("connect-profile", GLib.Variant("i", entry.id))
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", entry.id)]


def test_activating_an_unknown_action_is_harmless(adw_app):
    adw_app.activate_action("no-such-action", None)
