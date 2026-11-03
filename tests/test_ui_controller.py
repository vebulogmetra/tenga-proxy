"""AppController: оркестровка без GTK, проверяется с подменной оболочкой."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.core import core_pid
from src.core.connection import ConnectionResult
from src.core.context import AppContext
from src.core.main_loop import ImmediateLoop
from src.ui.controller import (
    BLOCK_RELEASED,
    BLOCK_RELEASED_AFTER_CRASH,
    CONFIRM_DELETE,
    CONFIRM_URL_CHANGE,
    CORE_EXIT_GAVE_UP,
    CORE_EXIT_RESTART,
    AppController,
    resume_monitoring,
)
from src.ui.logic.status import BLOCKED_BANNER, ConnectionState

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


@dataclass
class Confirm:
    kind: str
    heading: str
    body: str
    on_confirm: object
    confirm_label: str | None


@dataclass
class FakeShell:
    """Запоминает всё, что контроллер просит у интерфейса."""

    window: bool = True
    selected: int | None = None
    toasts: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    confirms: list[Confirm] = field(default_factory=list)
    enabled: dict[str, bool] = field(default_factory=dict)
    tray: list[tuple[ConnectionState, str]] = field(default_factory=list)
    forms: list[tuple] = field(default_factory=list)

    def toast(self, text, *, button=None, action=None):
        self.toasts.append((text, button, action))

    def notify(self, text):
        self.notifications.append(text)

    def has_window(self):
        return self.window

    def refresh_status(self):
        self.calls.append(("refresh_status",))

    def refresh_pages(self):
        self.calls.append(("refresh_pages",))

    def show_connecting(self, profile_name):
        self.calls.append(("show_connecting", profile_name))

    def show_error(self, message):
        self.calls.append(("show_error", message))

    def selected_profile_id(self):
        return self.selected

    def sort_by_ping(self):
        self.calls.append(("sort_by_ping",))

    def set_ping_progress(self, progress):
        self.calls.append(("set_ping_progress", progress))

    def update_group_progress(self, group_id):
        self.calls.append(("update_group_progress", group_id))

    def set_tray_state(self, state, profile_name):
        self.tray.append((state, profile_name))

    def set_action_enabled(self, name, enabled):
        self.enabled[name] = enabled

    def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None):
        self.confirms.append(Confirm(kind, heading, body, on_confirm, confirm_label))

    def open_subscription_form(self, name, url):
        self.forms.append(("subscription", name, url))

    def open_routing_import(self, rows, on_confirm):
        self.forms.append(("routing-import", rows, on_confirm))

    @property
    def last_toast(self) -> str:
        return self.toasts[-1][0] if self.toasts else ""

    def count(self, name: str) -> int:
        return sum(call[0] == name for call in self.calls)


@pytest.fixture
def made(tmp_path):
    context = AppContext(config_dir=tmp_path)
    # Настройки грузятся лениво; без загрузки `save_config` сохранять нечего.
    assert context.config is not None
    shell = FakeShell()
    loop = ImmediateLoop()
    return AppController(context, shell, loop), shell, loop


def add_profile(controller, group_id=None):
    from src.fmt import parse_link

    return controller.add_profile_from_bean(parse_link(LINK), group_id=group_id)


# --- сообщения ---


def test_notify_user_shows_a_toast_and_a_notification(made):
    controller, shell, _ = made

    controller.notify_user("переключаюсь")

    assert shell.last_toast == "переключаюсь"
    assert shell.notifications == ["переключаюсь"]


# --- данные ---


def test_add_profile_persists_refreshes_and_says_so(made):
    controller, shell, _ = made

    entry = add_profile(controller)

    assert controller.context.profiles.get_profile(entry.id) is not None
    assert shell.last_toast == f"Сервер добавлен: {entry.name}"
    assert shell.count("refresh_pages") == 1


def test_delete_missing_profile_only_toasts(made):
    controller, shell, _ = made

    controller.delete_profile(999)

    assert shell.last_toast == "Сервер не найден"
    assert shell.count("refresh_pages") == 0


def test_delete_profile_removes_it(made):
    controller, shell, _ = made
    entry = add_profile(controller)

    controller.delete_profile(entry.id)

    assert controller.context.profiles.get_profile(entry.id) is None
    assert shell.last_toast == f"Сервер удалён: {entry.name}"


def test_groups_are_added_renamed_and_deleted(made):
    controller, shell, _ = made

    group = controller.add_group("Свои")
    assert shell.last_toast == "Группа добавлена: Свои"

    controller.update_group(group.id, name="Чужие", url="https://sub.example/x")
    stored = controller.context.profiles.get_group(group.id)
    assert (stored.name, stored.subscription_url) == ("Чужие", "https://sub.example/x")

    controller.delete_group(group.id)
    assert controller.context.profiles.get_group(group.id) is None
    assert shell.last_toast == "Удалено: Чужие"


def test_update_missing_group_toasts(made):
    controller, shell, _ = made

    assert controller.update_group(42, name="x") is None
    assert shell.last_toast == "Группа не найдена"


def test_save_profiles_refreshes_pages_and_status(made):
    controller, shell, _ = made

    controller.save_profiles()

    assert shell.count("refresh_pages") == 1
    assert shell.count("refresh_status") == 1


def test_failed_persist_is_reported_not_raised(made, monkeypatch):
    controller, shell, _ = made
    monkeypatch.setattr(controller.context, "save_profiles", lambda: False)

    controller.add_group("Свои")

    assert ("Не удалось сохранить серверы", None, None) in shell.toasts


# --- настройки и маршрутизация ---


def test_apply_settings_saves_and_refreshes_status(made):
    controller, shell, _ = made

    assert controller.apply_settings() is True
    assert shell.count("refresh_status") == 1


def test_apply_settings_failure_toasts_and_returns_false(made, monkeypatch):
    controller, shell, _ = made
    monkeypatch.setattr(controller.context, "save_config", lambda: False)

    assert controller.apply_settings() is False
    assert shell.last_toast == "Не удалось сохранить настройки"


def test_restore_routing_action_follows_the_backup(made):
    controller, shell, _ = made

    controller.sync_restore_routing()
    assert shell.enabled["restore-routing"] is False

    controller.context.config.routing_backup = {"direct_list": []}
    controller.sync_restore_routing()
    assert shell.enabled["restore-routing"] is True


def test_restore_routing_without_backup_is_silent(made):
    controller, shell, _ = made

    controller.restore_routing()

    assert shell.toasts == []


# --- наблюдение ---


def test_resume_monitoring_starts_a_running_proxy(tmp_path):
    from unittest.mock import MagicMock

    context = AppContext(config_dir=tmp_path)
    monitor = MagicMock()
    context.set_monitor(monitor)
    context.proxy_state.is_running = True

    resume_monitoring(context)

    monitor.start.assert_called_once()


def test_shutdown_stops_the_connection_service(made):
    controller, _shell, _ = made
    stopped = []
    controller.set_connection_service(
        type("S", (), {"shutdown": lambda _self, thread: stopped.append(thread)})()
    )

    controller.shutdown()

    assert stopped == [None]


# --- подключение ---


class FakeService:
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

    def shutdown(self, thread):
        self._calls.append(("shutdown",))


def _wait(controller):
    if controller.connection_thread is not None:
        controller.connection_thread.join(5)


def test_connect_profile_runs_the_service_and_marks_the_profile_used(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))

    controller.connect_profile(entry.id)
    _wait(controller)

    assert calls == [("connect", entry.id)]
    assert ("show_connecting", entry.name) in shell.calls
    assert shell.tray[0] == (ConnectionState.CONNECTING, entry.name)
    assert shell.last_toast == f"Подключено: {entry.name}"
    assert controller.context.profiles.last_used_profile().id == entry.id
    assert shell.count("refresh_status") >= 1 and shell.count("refresh_pages") >= 1


def test_failed_connection_shows_the_error_everywhere(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.set_connection_service(FakeService([], ok=False, error="нет ядра"))

    controller.connect_profile(entry.id)
    _wait(controller)

    assert shell.last_toast == "Не удалось подключиться: нет ядра"
    assert ("show_error", "нет ядра") in shell.calls
    assert shell.tray[-1] == (ConnectionState.ERROR, "")


def test_connect_unknown_profile_only_toasts(made):
    controller, shell, _ = made

    controller.connect_profile(123)

    assert shell.last_toast == "Сервер не найден"
    assert controller.connection_thread is None


def test_connect_selected_falls_back_to_the_last_used_profile(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.context.profiles.mark_used(entry.id)
    calls = []
    controller.set_connection_service(FakeService(calls))
    shell.selected = None

    controller.connect_selected()
    _wait(controller)

    assert calls == [("connect", entry.id)]


def test_connect_selected_without_any_profile_asks_to_pick_one(made):
    controller, shell, _ = made

    controller.connect_selected()

    assert shell.last_toast == "Выберите сервер в списке"


def test_toggle_disconnects_a_running_proxy(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))
    controller.context.proxy_state.set_running(entry.id)

    controller.toggle_connection()
    _wait(controller)

    assert calls == [("disconnect",)]
    assert shell.last_toast == "Отключено"


def _watch_core(controller, monkeypatch, *, profile_id=1):
    """Подписать контроллер на выход ядра и вернуть сигнал, запросы и часы."""
    manager = MagicMock(is_running=False)
    controller.context._xray_manager = manager
    service = MagicMock()
    service.handle_core_exit.return_value = profile_id
    controller.set_connection_service(service)
    connected = []
    monkeypatch.setattr(controller, "connect_profile", connected.append)
    now = [1000.0]
    monkeypatch.setattr("src.ui.controller.time.monotonic", lambda: now[0])
    controller._watch_core()
    on_exit = manager.set_on_unexpected_exit.call_args[0][0]
    return on_exit, connected, now, manager, service


def test_connecting_subscribes_to_the_core_exit(made):
    """Менеджер создаётся лениво и без ядра падает, поэтому подписка — при подключении."""
    controller, _shell, _ = made
    entry = add_profile(controller)
    manager = MagicMock()
    controller.context._xray_manager = manager
    controller.set_connection_service(FakeService([]))

    controller.connect_profile(entry.id)
    _wait(controller)

    manager.set_on_unexpected_exit.assert_called_once()


def test_connecting_without_a_core_reaches_the_service(made, monkeypatch):
    """Ядра нет: об этом сообщает само подключение, подписка его не срывает."""
    controller, _shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))
    monkeypatch.setattr("src.core.config.find_xray_binary", lambda: None)
    monkeypatch.setattr("src.core.xray_manager.find_xray_binary", lambda: None)

    controller.connect_profile(entry.id)
    _wait(controller)

    assert calls == [("connect", entry.id)]


def test_core_exit_reconnects_the_same_profile_once(made, monkeypatch):
    controller, shell, _ = made
    on_exit, connected, now, _manager, _service = _watch_core(controller, monkeypatch)

    on_exit()

    assert connected == [1]
    assert CORE_EXIT_RESTART in shell.notifications

    now[0] += 30
    on_exit()

    assert connected == [1]
    assert CORE_EXIT_GAVE_UP in shell.notifications
    _service.release_block.assert_called_once()
    assert ("show_error", CORE_EXIT_GAVE_UP) in shell.calls
    assert shell.tray[-1] == (ConnectionState.ERROR, "")


def test_core_exit_restarts_again_after_the_cooldown(made, monkeypatch):
    controller, _shell, _ = made
    on_exit, connected, now, _manager, _service = _watch_core(controller, monkeypatch)

    on_exit()
    now[0] += 61
    on_exit()

    assert connected == [1, 1]


def test_core_exit_without_a_session_stays_quiet(made, monkeypatch):
    controller, shell, _ = made
    on_exit, connected, _now, _manager, _service = _watch_core(
        controller, monkeypatch, profile_id=-1
    )

    on_exit()

    assert connected == []
    assert shell.notifications == []


def test_core_exit_while_connecting_is_deferred(made, monkeypatch):
    """Сигнал пришёл, пока поток подключения жив: разобрать после него."""
    controller, _shell, _ = made
    on_exit, connected, _now, _manager, service = _watch_core(controller, monkeypatch)
    monkeypatch.setattr(controller, "connection_busy", lambda: True)

    on_exit()

    service.handle_core_exit.assert_not_called()

    monkeypatch.setattr(controller, "connection_busy", lambda: False)
    controller._on_connection_done(ConnectionResult(False, "x"), 1, "P")

    service.handle_core_exit.assert_called_once()
    assert connected == [1]


def test_deferred_core_exit_is_dropped_when_the_new_core_lives(made, monkeypatch):
    """Подключение, во время которого пришёл сигнал, подняло новое ядро."""
    controller, _shell, _ = made
    on_exit, connected, _now, manager, service = _watch_core(controller, monkeypatch)
    monkeypatch.setattr(controller, "connection_busy", lambda: True)

    on_exit()

    monkeypatch.setattr(controller, "connection_busy", lambda: False)
    manager.is_running = True
    controller._on_connection_done(ConnectionResult(False, "x"), 1, "P")

    service.handle_core_exit.assert_not_called()
    assert connected == []


def test_stale_core_exit_does_not_touch_a_living_core(made, monkeypatch):
    """Сигнал стоял в очереди главного цикла, а ядро уже поднято заново."""
    controller, _shell, _ = made
    on_exit, connected, _now, manager, service = _watch_core(controller, monkeypatch)
    manager.is_running = True

    on_exit()

    service.handle_core_exit.assert_not_called()
    assert connected == []


def test_core_exit_with_closed_traffic_gives_up_as_blocked(made, monkeypatch):
    controller, shell, _ = made
    entry = add_profile(controller)
    on_exit, connected, now, _manager, service = _watch_core(
        controller, monkeypatch, profile_id=entry.id
    )
    state = controller.context.proxy_state

    on_exit()
    state.traffic_blocked = True
    state.blocked_profile_id = entry.id
    now[0] += 30
    on_exit()

    assert connected == [entry.id]
    service.release_block.assert_not_called()
    assert BLOCKED_BANNER in shell.notifications
    assert CORE_EXIT_GAVE_UP not in shell.notifications
    assert shell.tray[-1] == (ConnectionState.BLOCKED, entry.name)


def test_failed_switch_with_closed_traffic_is_blocked_not_error(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    state = controller.context.proxy_state
    state.traffic_blocked = True
    state.blocked_profile_id = entry.id

    controller._on_connection_done(ConnectionResult(False, "нет ядра"), entry.id, entry.name)

    assert shell.tray[-1] == (ConnectionState.BLOCKED, entry.name)
    assert ("show_error", "нет ядра") in shell.calls


def test_toggle_while_blocked_connects_the_lost_server_not_the_selected(made, monkeypatch):
    """Случайный клик по логотипу не должен увести на другой сервер."""
    controller, shell, _ = made
    lost = add_profile(controller)
    other = add_profile(controller)
    shell.selected = other.id
    state = controller.context.proxy_state
    state.traffic_blocked = True
    state.blocked_profile_id = lost.id
    connected = []
    monkeypatch.setattr(controller, "connect_profile", connected.append)

    controller.toggle_connection()

    assert connected == [lost.id]


def test_toggle_while_blocked_on_a_deleted_server_falls_back_to_the_selected(made, monkeypatch):
    controller, shell, _ = made
    other = add_profile(controller)
    shell.selected = other.id
    state = controller.context.proxy_state
    state.traffic_blocked = True
    state.blocked_profile_id = 999
    connected = []
    monkeypatch.setattr(controller, "connect_profile", connected.append)

    controller.toggle_connection()

    assert connected == [other.id]


def test_release_block_goes_through_the_service(made):
    controller, shell, _ = made
    service = MagicMock()
    service.release_block.return_value = ConnectionResult(True)
    controller.set_connection_service(service)

    controller.release_block()
    _wait(controller)

    service.release_block.assert_called_once()
    assert shell.last_toast == BLOCK_RELEASED
    assert shell.tray[-1] == (ConnectionState.DISCONNECTED, "")


def test_release_block_waits_for_a_running_connection(made, monkeypatch):
    controller, shell, _ = made
    service = MagicMock()
    controller.set_connection_service(service)
    monkeypatch.setattr(controller, "connection_busy", lambda: True)

    controller.release_block()

    service.release_block.assert_not_called()
    assert shell.last_toast == "Подключение уже выполняется"


def test_block_released_at_start_is_reported_once(made):
    controller, shell, _ = made
    core_pid.note_block_released()

    controller.report_recovery()
    controller.report_recovery()

    assert shell.notifications == [BLOCK_RELEASED_AFTER_CRASH]


def test_nothing_to_report_at_a_normal_start(made):
    controller, shell, _ = made

    controller.report_recovery()

    assert shell.notifications == []


def test_connection_warning_reaches_the_user(made):
    controller, shell, _ = made
    entry = add_profile(controller)

    controller._on_connection_done(
        ConnectionResult(True, warning="IPv6 не заблокирован"), entry.id, entry.name
    )

    assert ("IPv6 не заблокирован", None, None) in shell.toasts


def test_select_profile_prefers_the_installed_handler(made):
    controller, _shell, _ = made
    seen = []
    controller.set_profile_activation_handler(seen.append)

    controller.select_profile(5)

    assert seen == [5]


def test_reconnect_current_restarts_the_running_profile(made):
    controller, _shell, _ = made
    entry = add_profile(controller)
    calls = []
    controller.set_connection_service(FakeService(calls))
    controller.context.proxy_state.set_running(entry.id)

    controller.reconnect_current()
    _wait(controller)

    assert calls == [("connect", entry.id)]


def test_watch_monitor_hands_failover_to_the_monitor(made):
    from unittest.mock import MagicMock

    controller, _shell, _ = made
    monitor = MagicMock()
    controller.context.set_monitor(monitor)

    controller.watch_monitor()

    monitor.set_on_status_changed.assert_called_once()
    assert controller._failover is not None


# --- подписки ---


def _wait_subscriptions(controller):
    if controller.subscriptions_thread is not None:
        controller.subscriptions_thread.join(5)


def test_add_subscription_creates_the_group_and_updates_it(made):
    controller, shell, _ = made
    updated = []
    controller.set_subscription_updater(lambda gid, url: updated.append((gid, url)) or 3)

    group = controller.add_subscription("Demo", "https://sub.example/list")
    _wait_subscriptions(controller)

    assert group.is_subscription and group.subscription_url == "https://sub.example/list"
    assert updated == [(group.id, "https://sub.example/list")]
    assert shell.last_toast == "Обновлено серверов: 3"


def test_update_subscription_without_url_toasts(made):
    controller, shell, _ = made
    group = controller.add_group("Обычная")

    controller.update_subscription(group.id)

    assert shell.last_toast == "У подписки нет адреса"
    assert controller.subscriptions_thread is None


def test_failed_update_reports_the_reason(made):
    controller, shell, _ = made

    def failing(_gid, _url):
        raise RuntimeError("boom")

    controller.set_subscription_updater(failing)
    controller.add_subscription("Demo", "https://sub.example/list")
    _wait_subscriptions(controller)

    assert shell.last_toast.startswith("Не удалось обновить подписки: ")
    assert controller._subscription_busy is False


def test_failed_update_offers_the_providers_fallback_url(made):
    controller, shell, _ = made
    group = controller.add_group("Demo")
    group.subscription_url = "https://sub.example/list"
    group.is_subscription = True
    group.sub_fallback_url = "https://backup.example/sub"

    def failing(_gid, _url):
        raise RuntimeError("boom")

    controller.set_subscription_updater(failing)
    controller.update_subscription(group.id)
    _wait_subscriptions(controller)

    assert shell.confirms[-1].kind == CONFIRM_URL_CHANGE
    assert "https://backup.example/sub" in shell.confirms[-1].body


def test_confirmed_url_change_switches_the_group_and_refreshes(made):
    controller, shell, _ = made
    group = controller.add_group("Demo")
    group.subscription_url = "https://sub.example/list"
    group.is_subscription = True
    group.sub_fallback_url = "https://backup.example/sub"
    seen = []

    def updater(_gid, url):
        seen.append(url)
        if url.startswith("https://sub."):
            raise RuntimeError("boom")
        return 1

    controller.set_subscription_updater(updater)
    controller.update_subscription(group.id)
    _wait_subscriptions(controller)
    shell.confirms[-1].on_confirm()
    _wait_subscriptions(controller)

    assert controller.context.profiles.get_group(group.id).subscription_url == (
        "https://backup.example/sub"
    )
    assert seen == ["https://sub.example/list", "https://backup.example/sub"]


PRIMARY_URL = "https://sub.example/list"
BACKUP_URL = "https://backup.example/sub"


def _subscription_response(body="", status=200, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response._content_consumed = True
    response.headers = headers or {}
    return response


def _fallback_group(controller):
    group = controller.add_group("Demo")
    group.subscription_url = PRIMARY_URL
    group.is_subscription = True
    group.sub_fallback_url = BACKUP_URL
    return group


def _run_update(controller, group, routes):
    def pinned_get(url, **_kwargs):
        return routes[url]

    with patch("src.sub.updater.pinned_get", pinned_get):
        controller.update_subscription(group.id)
        _wait_subscriptions(controller)


def test_an_update_through_the_fallback_keeps_the_address_and_asks(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response(LINK),
        },
    )

    assert group.subscription_url == PRIMARY_URL
    assert group.sub_via_fallback is True
    assert shell.last_toast == "Обновлено серверов: 1"
    assert shell.confirms[-1].kind == CONFIRM_URL_CHANGE
    assert "серверы загружены с запасного" in shell.confirms[-1].body
    assert BACKUP_URL in shell.confirms[-1].body


def test_a_new_address_goes_before_the_fallback_question(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response(
                LINK, headers={"new-url": "https://new.example/sub"}
            ),
        },
    )

    assert len(shell.confirms) == 1
    assert "https://new.example/sub" in shell.confirms[-1].body
    assert "сообщил новый адрес" in shell.confirms[-1].body


def test_both_addresses_failing_shows_the_error_without_a_question(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response("down", status=502),
        },
    )

    assert shell.last_toast == "Не удалось обновить подписки: сервер ответил 503"
    assert shell.confirms == []


@pytest.mark.parametrize("status", [404, 410])
def test_a_revoked_token_offers_no_address_change(made, status):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(controller, group, {PRIMARY_URL: _subscription_response("no", status=status)})

    assert shell.confirms == []


def test_another_failure_still_offers_the_address(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(controller, group, {PRIMARY_URL: _subscription_response("no", status=401)})

    assert "Обновить подписку «Demo» не удалось" in shell.confirms[-1].body


def test_refreshing_all_follows_the_same_rule_for_a_revoked_token(made):
    controller, shell, _ = made
    _fallback_group(controller)
    routes = {PRIMARY_URL: _subscription_response("no", status=404)}

    with patch("src.sub.updater.pinned_get", lambda url, **_kwargs: routes[url]):
        controller.refresh_subscriptions()
        _wait_subscriptions(controller)

    assert shell.confirms == []


def test_a_changed_address_forgets_the_previous_providers_fallback(made):
    controller, _shell, _ = made
    group = _fallback_group(controller)
    group.sub_via_fallback = True

    controller.update_group(group.id, name="Demo", url="https://other.example/sub")

    assert group.sub_fallback_url == ""
    assert group.sub_via_fallback is False


def test_renaming_keeps_the_fallback(made):
    controller, _shell, _ = made
    group = _fallback_group(controller)

    controller.update_group(group.id, name="Новое", url=PRIMARY_URL)
    controller.update_group(group.id, name="Ещё новее")

    assert group.sub_fallback_url == BACKUP_URL


def test_refresh_subscriptions_without_any_toasts(made):
    controller, shell, _ = made

    controller.refresh_subscriptions()

    assert shell.last_toast == "Подписок нет"


def test_refresh_subscriptions_sums_the_groups(made):
    controller, shell, _ = made
    controller.set_subscription_updater(lambda _gid, _url: 2)
    for name in ("A", "B"):
        group = controller.add_group(name)
        group.is_subscription = True
        group.subscription_url = f"https://{name}.example/sub"

    controller.refresh_subscriptions()
    _wait_subscriptions(controller)

    assert shell.last_toast == "Обновлено серверов: 4"


# --- замер задержки ---


def _wait_latency(controller):
    if controller.latency_runner is not None:
        controller.latency_runner.wait(5)


def test_test_latency_probes_every_profile_and_stores_the_result(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    probed = []
    controller.set_latency_probe(lambda pid: probed.append(pid) or 55)

    controller.test_latency()
    _wait_latency(controller)

    assert probed == [entry.id]
    assert controller.context.profiles.get_profile(entry.id).latency_ms == 55
    assert shell.last_toast == "Проверка задержки завершена"
    assert ("set_ping_progress", None) in shell.calls


def test_test_latency_without_profiles_toasts(made):
    controller, shell, _ = made
    controller.set_latency_probe(lambda _pid: 1)

    controller.test_latency()

    assert shell.last_toast == "Нет серверов для проверки"


def test_probe_is_refused_while_tun_is_active(made):
    controller, shell, _ = made
    entry = add_profile(controller)
    controller.set_latency_probe(lambda _pid: 1)
    controller.context.proxy_state.set_running(entry.id, mode="tun")

    controller.test_latency_for(entry.id)

    assert shell.last_toast.startswith("Замер при активном TUN недоступен")


def test_group_run_sorts_by_ping_and_coalesces_redraws(made):
    controller, shell, loop = made
    group = controller.add_group("G")
    first = add_profile(controller, group_id=group.id)
    second = add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda pid: 10 if pid == first.id else 20)

    controller.test_latency_for_group(group.id)
    _wait_latency(controller)

    assert ("sort_by_ping",) in shell.calls
    assert controller.context.profiles.get_profile(second.id).latency_ms == 20
    # Отложенная перерисовка снята итоговой: таймер отменён, не сработал.
    assert loop.scheduled == [] and len(loop.cancelled) >= 1


def test_keep_working_asks_before_removing_dead_profiles(made):
    controller, shell, _ = made
    group = controller.add_group("G")
    alive = add_profile(controller, group_id=group.id)
    dead = add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda pid: 30 if pid == alive.id else -1)

    controller.keep_working_profiles(group.id)
    _wait_latency(controller)

    confirm = shell.confirms[-1]
    assert confirm.kind == CONFIRM_DELETE and confirm.confirm_label == "Оставить рабочие"
    confirm.on_confirm()
    assert controller.context.profiles.get_profile(dead.id) is None
    assert controller.context.profiles.get_profile(alive.id) is not None


def test_keep_working_is_cancelled_without_network(tmp_path):
    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    controller = AppController(context, shell, ImmediateLoop(), network_available=lambda: False)
    group = controller.add_group("G")
    add_profile(controller, group_id=group.id)
    controller.set_latency_probe(lambda _pid: -1)

    controller.keep_working_profiles(group.id)
    _wait_latency(controller)

    assert shell.confirms == []
    assert shell.last_toast.startswith("Фильтрация отменена")


# --- обновления и ссылки ---


def test_app_update_is_notified_once(tmp_path):
    from tests.test_core_app_update import RELEASE

    context = AppContext(config_dir=tmp_path)
    shell = FakeShell()
    controller = AppController(context, shell, ImmediateLoop(), app_version=lambda: "0.16.2")
    calls = []
    controller.set_app_release_fetcher(lambda: calls.append(True) or [RELEASE])

    controller.refresh_app_releases_if_due()
    controller.app_update_thread.join(5)
    controller.refresh_app_releases_if_due()

    assert context.config.app_update_notified == "v0.17.0"
    assert shell.last_toast == "Доступна версия v0.17.0. Откройте настройки → О программе"
    assert calls == [True]


def test_app_update_is_skipped_without_a_fetcher(made):
    controller, _shell, _ = made

    controller.refresh_app_releases_if_due()

    assert controller.app_update_thread is None


def test_core_releases_are_refreshed_when_due(made, monkeypatch):
    controller, _shell, _ = made
    monkeypatch.setattr("src.ui.controller.is_check_due", lambda _config, _now: True)
    seen = []
    monkeypatch.setattr(
        "src.ui.controller.refresh_known_releases",
        lambda _config, **kwargs: seen.append(kwargs["fetch"]()) or None,
    )
    controller.set_release_fetcher(lambda: ["r"])

    controller.refresh_core_releases_if_due()
    controller.core_update_thread.join(5)

    assert seen == [["r"]]


def test_subscription_link_opens_the_form_prefilled(made):
    from urllib.parse import quote

    controller, shell, _ = made

    controller.import_app_link(
        "veblock://add/" + quote("https://example.com/sub", safe="") + "#Example"
    )

    assert shell.forms == [("subscription", "Example", "https://example.com/sub")]


def test_routing_link_asks_for_confirmation_then_applies(made):
    import base64
    import json

    controller, shell, _ = made
    payload = base64.urlsafe_b64encode(
        json.dumps({"DirectSites": ["example.org"], "GlobalProxy": False}).encode()
    ).decode()

    controller.import_app_link("happ://routing/add/" + payload)

    kind, rows, on_confirm = shell.forms[-1]
    assert kind == "routing-import" and rows
    on_confirm()
    assert "example.org" in controller.context.config.routing.direct_list
    assert shell.toasts[-1] == ("Маршрутизация импортирована", "Вернуть", "app.restore-routing")
    assert shell.enabled["restore-routing"] is True


def test_broken_link_only_toasts(made):
    controller, shell, _ = made

    controller.import_app_link("veblock://add/\x01")

    assert shell.last_toast and shell.forms == []


# --- интерфейс VPN ---


class WatchedService:
    """Служба подключения с VPN в таблице; интерфейс подменяет тест."""

    def __init__(self, interface, changed=True, vpn="corp"):
        self.interface = interface
        self.changed = changed
        self.vpn = vpn
        self.followed = []

    def watched_vpn(self):
        return self.vpn

    def probe_vpn_interface(self, name):
        if isinstance(self.interface, Exception):
            raise self.interface
        return self.interface

    def follow_vpn_interface(self, name, interface):
        self.followed.append((name, interface))
        return self.changed

    def shutdown(self, _thread):
        pass


def _vpn_check(controller, service, monkeypatch):
    controller._connection_service = service
    reconnects = []
    monkeypatch.setattr(controller, "reconnect_current", lambda: reconnects.append(True))
    assert controller._check_vpn_interface() is True, "Таймер должен жить дальше"
    if controller.vpn_probe_thread is not None:
        controller.vpn_probe_thread.join(5)
    return reconnects


def test_new_vpn_interface_moves_the_table_and_reconnects(made, monkeypatch):
    controller, _, _ = made
    service = WatchedService("tun1")

    assert _vpn_check(controller, service, monkeypatch) == [True]
    assert service.followed == [("corp", "tun1")]


def test_unchanged_vpn_interface_does_not_reconnect(made, monkeypatch):
    controller, _, _ = made

    assert _vpn_check(controller, WatchedService("tun0", changed=False), monkeypatch) == []


@pytest.mark.parametrize("interface", [None, RuntimeError("nmcli")])
def test_vpn_without_an_interface_keeps_the_table(made, monkeypatch, interface):
    """VPN переподключается: подождём, а сбой проверки не должен останавливать следующие."""
    controller, _, _ = made
    service = WatchedService(interface)

    _vpn_check(controller, service, monkeypatch)

    assert service.followed == []
    assert controller._vpn_probe_running is False


def test_nothing_to_watch_does_not_start_a_probe(made, monkeypatch):
    controller, _, _ = made

    _vpn_check(controller, WatchedService("tun1", vpn=None), monkeypatch)

    assert controller.vpn_probe_thread is None


def test_busy_connection_postpones_the_vpn_check(made, monkeypatch):
    """Таблицу меняет поток подключения: второго писателя быть не должно."""
    controller, _, _ = made
    monkeypatch.setattr(controller, "connection_busy", lambda: True)

    _vpn_check(controller, WatchedService("tun1"), monkeypatch)

    assert controller.vpn_probe_thread is None


def test_vpn_watch_starts_once_and_stops_on_shutdown(made):
    controller, _, loop = made
    controller._connection_service = WatchedService("tun0")

    controller._watch_vpn_interface()
    controller._watch_vpn_interface()
    assert len(loop.scheduled) == 1

    handle = loop.scheduled[0]
    controller.shutdown()
    assert handle in loop.cancelled
