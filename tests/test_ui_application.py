"""Tests for the Adw.Application shell."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_a_failed_update_explains_the_reason_without_the_address(adw_app):
    import requests

    adw_app.activate()
    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/secret-token"

    def failing(_group_id: int, url: str) -> int:
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    adw_app.set_subscription_updater(failing)
    adw_app.update_subscription(group.id)
    adw_app.wait_for_subscriptions_for_test()

    assert adw_app.last_toast_for_test == (
        "Не удалось обновить подписки: нет связи с сервером подписки"
    )


def test_a_denied_update_shows_the_providers_explanation(adw_app):
    from src.sub.errors import SubscriptionHttpError

    adw_app.activate()
    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    group.subscription_url = "https://sub.example/list"

    def denied(_group_id: int, _url: str) -> int:
        raise SubscriptionHttpError(403, "Превышен лимит устройств")

    adw_app.set_subscription_updater(denied)
    adw_app.update_subscription(group.id)
    adw_app.wait_for_subscriptions_for_test()

    assert "403: Превышен лимит устройств" in adw_app.last_toast_for_test


def test_the_default_updater_goes_through_the_running_proxy(adw_app):
    """В режиме системного прокси requests сам его не видит: адрес передаётся явно."""
    from unittest.mock import Mock, patch

    from src.db.config import ProxyMode

    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    adw_app.context.proxy_state.set_running(1, mode=ProxyMode.SYSTEM_PROXY)

    response = Mock()
    response.text = "vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp#A"
    response.raise_for_status = Mock()

    with patch("src.sub.updater.requests.get", return_value=response) as mock_get:
        count = adw_app._default_subscription_updater(group.id, "https://sub.example/list")

    assert count == 1
    assert mock_get.call_args.kwargs["proxies"] == {
        "http": "http://127.0.0.1:2081",
        "https": "http://127.0.0.1:2081",
    }


# --- предложение сменить адрес подписки ---

OLD_URL = "https://old.example/sub"
NEW_URL = "https://new.example/sub"


def _update_with_response_headers(adw_app, headers: dict[str, str]):
    """Run the real updater against a canned HTTP response."""
    from unittest.mock import Mock, patch

    adw_app.activate()
    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    group.subscription_url = OLD_URL

    body = "vless://11111111-1111-1111-1111-111111111111@h.example:443?type=tcp#A"
    response = Mock()
    response.text = body
    response.content = body.encode("utf-8")
    response.headers = headers
    response.raise_for_status = Mock()

    with patch("src.sub.updater.requests.get", return_value=response):
        adw_app.update_subscription(group.id)
        adw_app.wait_for_subscriptions_for_test()
    return group


def test_a_new_address_is_offered_but_not_applied(adw_app):
    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})

    assert adw_app.current_dialog is not None
    assert NEW_URL in adw_app.current_dialog.get_body()
    assert group.subscription_url == OLD_URL


def test_confirming_switches_the_subscription_to_the_new_address(adw_app):
    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})
    updated: list[str] = []
    adw_app.set_subscription_updater(lambda _gid, url: updated.append(url) or 1)

    adw_app.current_dialog.emit("response", "change")
    adw_app.wait_for_subscriptions_for_test()

    assert group.subscription_url == NEW_URL
    # После смены подписка сразу обновляется уже с нового адреса.
    assert updated == [NEW_URL]


def test_declining_keeps_the_old_address(adw_app):
    group = _update_with_response_headers(adw_app, {"new-url": NEW_URL})

    adw_app.current_dialog.emit("response", "cancel")

    assert group.subscription_url == OLD_URL


def test_an_ordinary_update_asks_nothing(adw_app):
    _update_with_response_headers(adw_app, {})

    assert adw_app.current_dialog is None


def test_a_failed_update_offers_the_fallback_address(adw_app):
    import requests

    adw_app.activate()
    group = adw_app.context.profiles.add_group("Подписка", is_subscription=True)
    group.subscription_url = OLD_URL
    group.sub_fallback_url = "https://backup.example/sub"

    def failing(_group_id: int, _url: str) -> int:
        raise requests.ConnectionError("blocked")

    adw_app.set_subscription_updater(failing)
    adw_app.update_subscription(group.id)
    adw_app.wait_for_subscriptions_for_test()

    assert adw_app.current_dialog is not None
    assert "https://backup.example/sub" in adw_app.current_dialog.get_body()
    assert group.subscription_url == OLD_URL


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


def test_connect_without_a_selection_reuses_the_last_profile(adw_app):
    """После отключения «Подключить» берёт последний использованный профиль."""
    adw_app.activate()
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))

    adw_app.select_profile(entry.id)
    adw_app.wait_for_connection_for_test()
    adw_app.get_active_window().profiles_page.column_view.get_model().unselect_all()

    adw_app.activate_action("connect", None)
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", entry.id), ("connect", entry.id)]


def test_a_failed_connection_is_not_remembered(adw_app):
    adw_app.activate()
    entry = add_profile(adw_app)
    adw_app.set_connection_service(FakeService([], ok=False, error="нет"))

    adw_app.select_profile(entry.id)
    adw_app.wait_for_connection_for_test()

    assert adw_app.context.profiles.last_used_profile() is None


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


# --- трей (этап 4) ---


def test_the_tray_is_off_unless_asked_for(adw_app):
    assert adw_app.tray is None


def test_start_tray_publishes_an_item(adw_app):
    from tests.support.tray import FakeTrayItem

    item = FakeTrayItem()
    adw_app.start_tray(item=item)
    try:
        assert adw_app.tray is not None
        assert item.published is True
    finally:
        adw_app.stop_tray()


def test_starting_the_tray_twice_keeps_one_item(adw_app):
    from tests.support.tray import FakeTrayItem

    first = FakeTrayItem()
    second = FakeTrayItem()
    adw_app.start_tray(item=first)
    try:
        adw_app.start_tray(item=second)

        assert second.published is False
    finally:
        adw_app.stop_tray()


def test_connecting_moves_the_tray_into_the_connecting_state(adw_app):
    from tests.support.tray import FakeTrayItem

    adw_app.activate()
    item = FakeTrayItem()
    adw_app.start_tray(item=item)
    entry = add_profile(adw_app)
    adw_app.set_connection_service(FakeService([]))
    try:
        adw_app.connect_profile(entry.id)

        # Промежуточное состояние есть только в UI, из proxy_state его не видно.
        assert item.icons[-1] == "tenga-proxy-connecting"
        adw_app.wait_for_connection_for_test()
    finally:
        adw_app.stop_tray()


def test_a_failed_connection_moves_the_tray_into_the_error_state(adw_app):
    from tests.support.tray import FakeTrayItem

    adw_app.activate()
    item = FakeTrayItem()
    adw_app.start_tray(item=item)
    entry = add_profile(adw_app)
    adw_app.set_connection_service(FakeService([], ok=False, error="нет сети"))
    try:
        adw_app.connect_profile(entry.id)
        adw_app.wait_for_connection_for_test()

        assert item.tooltips[-1] == "Tenga Proxy: ошибка"
    finally:
        adw_app.stop_tray()


def test_the_tray_menu_reaches_the_application_actions(adw_app):
    from tests.support.tray import FakeTrayItem, find_item

    adw_app.activate()
    item = FakeTrayItem()
    adw_app.start_tray(item=item)
    entry = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))
    try:
        adw_app.tray.refresh()
        menu_entry = find_item(item.menus[-1], entry.name)
        item.on_activate(menu_entry.action, menu_entry.target)
        adw_app.wait_for_connection_for_test()

        assert calls == [("connect", entry.id)]
    finally:
        adw_app.stop_tray()


def test_stop_tray_removes_the_controller(adw_app):
    from tests.support.tray import FakeTrayItem

    item = FakeTrayItem()
    adw_app.start_tray(item=item)

    adw_app.stop_tray()

    assert adw_app.tray is None
    assert item.stopped is True


def test_stop_tray_without_a_tray_is_safe(adw_app):
    adw_app.stop_tray()


def test_a_tray_that_cannot_start_does_not_break_the_application(adw_app, monkeypatch):
    """Без панели с поддержкой SNI приложение обязано запуститься."""
    from src.ui.tray import controller as controller_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("no bus")

    monkeypatch.setattr(controller_module, "TrayController", explode)

    adw_app.start_tray()

    assert adw_app.tray is None


def test_default_latency_run_measures_the_whole_set_with_one_batch_call(adw_app, monkeypatch):
    """Без подменённой пробы замер идёт пакетом: один вызов на все профили."""
    first = add_profile(adw_app)
    second = add_profile(adw_app)
    calls: list[list[int]] = []

    def fake_probe_profiles(profiles, *, settings, binary_path, on_result):
        calls.append([profile.id for profile in profiles])
        for profile in profiles:
            on_result(profile.id, 42)

    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)
    monkeypatch.setattr(
        type(adw_app.context),
        "xray_manager",
        property(lambda _self: SimpleNamespace(binary_path="xray")),
    )

    adw_app.activate_action("test-latency", None)
    adw_app.wait_for_latency_for_test()

    store = adw_app.context.profiles
    assert calls == [[first.id, second.id]]
    assert store.get_profile(first.id).latency_ms == 42
    assert store.get_profile(second.id).latency_ms == 42


def _silent_server_status():
    from src.core.monitor import ConnectionStatus

    return ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=True)


def _watched_monitor(app, *, failover_enabled: bool):
    from src.core.monitor import attach_monitor

    context = app.context
    context.config.monitoring.failover_enabled = failover_enabled
    context.config.monitoring.failover_threshold = 1
    monitor = attach_monitor(context)
    app.watch_monitor()
    return monitor


def test_failover_connects_the_next_profile_of_the_group_and_says_so(adw_app):
    first = add_profile(adw_app)
    second = add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))
    adw_app.context.proxy_state.set_running(first.id)
    monitor = _watched_monitor(adw_app, failover_enabled=True)

    monitor._status = _silent_server_status()
    monitor._notify_status_changed()
    adw_app.wait_for_connection_for_test()

    assert calls == [("connect", second.id)]
    assert "переключаюсь" in adw_app.last_notification_for_test


def test_failover_stays_out_of_the_way_when_disabled(adw_app):
    first = add_profile(adw_app)
    add_profile(adw_app)
    calls = []
    adw_app.set_connection_service(FakeService(calls))
    adw_app.context.proxy_state.set_running(first.id)
    monitor = _watched_monitor(adw_app, failover_enabled=False)

    monitor._status = _silent_server_status()
    monitor._notify_status_changed()
    adw_app.wait_for_connection_for_test()

    assert calls == []
    assert adw_app.last_notification_for_test == ""


def test_core_releases_are_refreshed_on_activation_when_the_check_is_due(adw_app):
    from src.core.core_update import KnownReleases

    adw_app.set_release_fetcher(lambda: KnownReleases(stable="26.3.27", prerelease="26.9.30"))

    adw_app.activate()
    adw_app.wait_for_core_update_for_test()

    config = adw_app.context.config
    assert config.core_update_prerelease == "26.9.30"
    assert config.core_update_checked_at > 0


def test_core_releases_are_not_requested_before_the_interval_passes(adw_app):
    import time

    calls: list = []
    adw_app.context.config.core_update_checked_at = int(time.time())
    adw_app.set_release_fetcher(lambda: calls.append(True))

    adw_app.activate()
    adw_app.wait_for_core_update_for_test()

    assert calls == []


def test_core_releases_are_never_requested_without_a_fetcher(adw_app):
    """Сеть включает только `run_app`: тесты и встраивание в неё не ходят."""
    adw_app.activate()
    adw_app.wait_for_core_update_for_test()

    assert adw_app.context.config.core_update_checked_at == 0


def _simulate_close(app, dialog) -> None:
    """Release the slot the way the `closed` signal would.

    Настоящее закрытие в тестах недостижимо: `Adw.Dialog` уходит с экрана
    анимацией, а она не проигрывается, пока окно не отрисовано композитором,
    и `close()` вместе с `force_close()` остаются без эффекта. Проверяется
    поэтому сам механизм слота, а не анимация libadwaita.
    """
    app._on_dialog_closed(dialog)


def test_a_second_dialog_does_not_stack_on_the_first(adw_app):
    """Повторное действие не кладёт второй диалог поверх первого."""
    adw_app.activate()

    adw_app.activate_action("add-profile")
    first = adw_app.current_dialog
    assert first is not None

    adw_app.activate_action("add-profile")

    assert adw_app.current_dialog is first
    _simulate_close(adw_app, first)


def test_a_different_action_does_not_open_over_an_open_dialog(adw_app):
    adw_app.activate()

    adw_app.activate_action("add-profile")
    first = adw_app.current_dialog
    adw_app.activate_action("settings")

    assert adw_app.current_dialog is first
    _simulate_close(adw_app, first)


def test_closing_a_dialog_frees_the_slot(adw_app):
    adw_app.activate()

    adw_app.activate_action("add-profile")
    first = adw_app.current_dialog
    _simulate_close(adw_app, first)

    assert adw_app.current_dialog is None

    adw_app.activate_action("add-subscription")
    second = adw_app.current_dialog

    assert second is not None
    assert second is not first
    _simulate_close(adw_app, second)


def test_present_dialog_reports_whether_it_showed(adw_app):
    from src.ui.dialogs.group import GroupDialog

    adw_app.activate()
    first = GroupDialog()

    assert adw_app.present_dialog(first) is True
    assert adw_app.present_dialog(GroupDialog()) is False

    _simulate_close(adw_app, first)

    assert adw_app.present_dialog(GroupDialog()) is True
    _simulate_close(adw_app, adw_app.current_dialog)


def test_a_stale_close_does_not_free_a_newer_dialog(adw_app):
    """Сигнал от уже закрытого диалога не выбивает следующий из слота."""
    from src.ui.dialogs.group import GroupDialog

    adw_app.activate()
    first = GroupDialog()
    adw_app.present_dialog(first)
    _simulate_close(adw_app, first)

    second = GroupDialog()
    adw_app.present_dialog(second)
    _simulate_close(adw_app, first)

    assert adw_app.current_dialog is second
    _simulate_close(adw_app, second)


def test_the_dialog_slot_is_cleared_between_tests(adw_app):
    """reset_for_tests обязан отпускать слот: иначе он течёт между тестами."""
    from src.ui.dialogs.group import GroupDialog

    adw_app.activate()
    adw_app.present_dialog(GroupDialog())

    adw_app.reset_for_tests(adw_app.context)

    assert adw_app.current_dialog is None


def _add(store, group_id, name):
    return store.parse_and_add_link(
        f"vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#{name}",
        group_id=group_id,
    )


def test_group_latency_probes_only_that_group(adw_app):
    """Пинг группы меряет её профили, а не весь список."""
    adw_app.activate()
    store = adw_app.context.profiles
    target = store.add_group("Целевая")
    other = store.add_group("Посторонняя")
    inside = _add(store, target.id, "Внутри")
    outside = _add(store, other.id, "Снаружи")

    probed: list[int] = []

    def fake_probe(profile_id: int) -> int:
        probed.append(profile_id)
        return 42

    adw_app.set_latency_probe(fake_probe)
    adw_app.test_latency_for_group(target.id)
    adw_app.wait_for_latency_for_test()

    assert probed == [inside.id]
    assert store.get_profile(outside.id).latency_ms == -1


def test_group_latency_sorts_profiles_while_running(adw_app):
    """Результаты пинга должны пересортировывать список по ходу замера."""
    adw_app.activate()
    store = adw_app.context.profiles
    group = store.add_group("Целевая")
    slow = _add(store, group.id, "Медленный")
    fast = _add(store, group.id, "Быстрый")

    latencies = {slow.id: 300, fast.id: 20}
    adw_app.set_latency_probe(lambda pid: latencies[pid])

    page = adw_app.get_active_window().profiles_page
    adw_app.test_latency_for_group(group.id)
    adw_app.wait_for_latency_for_test()

    from src.ui.logic.profiles_view import SortKey

    assert page.get_sort_key_for_test() is SortKey.PING
    assert page.get_profile_titles(group_id=group.id) == ["Быстрый", "Медленный"]


def test_url_change_confirmation_defaults_to_keeping_the_address(gtk_ready):
    from src.ui.dialogs.confirm import build_url_change_confirmation

    confirmed = []
    dialog = build_url_change_confirmation(
        "Сменить?", "https://e.com/?a=1&b=2", lambda: confirmed.append(True)
    )
    assert dialog.get_default_response() == "cancel"
    assert dialog.get_close_response() == "cancel"
    assert not dialog.get_body_use_markup()
    dialog.emit("response", "cancel")
    assert confirmed == []
