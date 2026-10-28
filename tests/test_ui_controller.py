"""AppController: оркестровка без GTK, проверяется с подменной оболочкой."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.core.context import AppContext
from src.core.main_loop import ImmediateLoop
from src.ui.controller import CONFIRM_DELETE, CONFIRM_URL_CHANGE, AppController, resume_monitoring
from src.ui.logic.status import ConnectionState

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
    assert shell.last_toast == f"Профиль добавлен: {entry.name}"
    assert shell.count("refresh_pages") == 1


def test_delete_missing_profile_only_toasts(made):
    controller, shell, _ = made

    controller.delete_profile(999)

    assert shell.last_toast == "Профиль не найден"
    assert shell.count("refresh_pages") == 0


def test_delete_profile_removes_it(made):
    controller, shell, _ = made
    entry = add_profile(controller)

    controller.delete_profile(entry.id)

    assert controller.context.profiles.get_profile(entry.id) is None
    assert shell.last_toast == f"Профиль удалён: {entry.name}"


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

    assert ("Не удалось сохранить профили", None, None) in shell.toasts


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

    assert shell.last_toast == "Профиль не найден"
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

    assert shell.last_toast == "Выберите профиль в списке"


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
    assert shell.last_toast == "Обновлено профилей: 3"


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

    assert shell.last_toast == "Обновлено профилей: 4"


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

    assert shell.last_toast == "Нет профилей для проверки"


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
