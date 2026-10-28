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
