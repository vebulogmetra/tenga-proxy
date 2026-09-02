"""Состав меню трея для разных состояний."""

from __future__ import annotations

from dataclasses import dataclass

from src.ui.logic.status import ConnectionState
from src.ui.tray.menu import MAX_PROFILES, build_menu


@dataclass
class FakeProfile:
    id: int
    name: str


def _labels(items):
    return [item.label for item in items]


def _find(items, label):
    for item in items:
        if item.label == label:
            return item
        found = _find(item.children, label)
        if found is not None:
            return found
    return None


def test_the_first_entry_shows_the_disconnected_status():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert items[0].label == "Статус: Отключено"


def test_the_status_entry_is_not_clickable():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert items[0].enabled is False


def test_the_status_entry_names_the_connected_profile():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Работа")

    assert items[0].label == "Статус: Работа"


def test_the_connecting_state_has_its_own_status_line():
    items = build_menu(ConnectionState.CONNECTING, [], profile_name="Работа")

    assert items[0].label == "Статус: подключение…"


def test_disconnected_offers_to_connect():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Подключить") is not None


def test_connected_offers_to_disconnect():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Работа")

    assert _find(items, "Отключить") is not None
    assert _find(items, "Подключить") is None


def test_the_connect_entry_triggers_the_application_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Подключить").action == "app.connect"


def test_the_disconnect_entry_triggers_the_application_action():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Р")

    assert _find(items, "Отключить").action == "app.disconnect"


def test_connecting_offers_to_cancel():
    items = build_menu(ConnectionState.CONNECTING, [], profile_name="Работа")

    assert _find(items, "Отменить") is not None


def test_the_profiles_submenu_lists_the_profiles():
    profiles = [FakeProfile(1, "Первый"), FakeProfile(2, "Второй")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")

    assert _labels(_find(items, "Профили").children) == ["Первый", "Второй"]


def test_a_profile_entry_carries_its_id_as_the_target():
    profiles = [FakeProfile(7, "Седьмой")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")
    entry = _find(items, "Седьмой")

    assert entry.action == "app.connect-profile"
    assert entry.target == 7


def test_the_running_profile_is_marked_as_checked():
    profiles = [FakeProfile(1, "Первый"), FakeProfile(2, "Второй")]

    items = build_menu(
        ConnectionState.CONNECTED, profiles, profile_name="Второй", active_profile_id=2
    )

    assert _find(items, "Второй").checked is True
    assert _find(items, "Первый").checked is False


def test_no_profile_is_checked_when_nothing_runs():
    profiles = [FakeProfile(1, "Первый")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")

    assert _find(items, "Первый").checked is False


def test_the_submenu_says_so_when_there_are_no_profiles():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")
    children = _find(items, "Профили").children

    assert _labels(children) == ["(нет профилей)"]
    assert children[0].enabled is False


def test_the_profile_list_is_capped():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    # Меню в 130 пунктов панель растягивает на весь экран, поэтому список
    # обрезается, а полный остаётся в окне.
    assert len(children) == MAX_PROFILES + 1


def test_the_capped_list_ends_with_a_link_to_the_window():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    assert children[-1].label == "Показать все…"
    assert children[-1].action == "app.activate-window"


def test_a_short_list_has_no_link_to_the_window():
    profiles = [FakeProfile(1, "Один")]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    assert _labels(children) == ["Один"]


def test_the_running_profile_stays_visible_beyond_the_cap():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]
    last_id = profiles[-1].id

    children = _find(
        build_menu(ConnectionState.CONNECTED, profiles, "P99", active_profile_id=last_id),
        "Профили",
    ).children

    # Иначе подключённый профиль пропал бы из меню ровно тогда, когда он важнее
    # всего.
    assert any(child.target == last_id for child in children)


def test_the_menu_offers_the_standard_application_entries():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    for label in ("Добавить профиль…", "Открыть окно", "Настройки…", "Выход"):
        assert _find(items, label) is not None, label


def test_the_quit_entry_triggers_the_quit_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Выход").action == "app.quit"


def test_the_window_entry_triggers_the_activate_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Открыть окно").action == "app.activate-window"


def test_the_menu_is_split_by_separators():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert sum(1 for item in items if item.is_separator) >= 3


def test_a_long_profile_name_is_shortened():
    profiles = [FakeProfile(1, "О" * 80)]

    entry = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children[0]

    # Панель не переносит строки: длинное имя растянуло бы меню на весь экран.
    assert len(entry.label) <= 40
    assert entry.label.endswith("…")


def test_a_short_profile_name_is_untouched():
    profiles = [FakeProfile(1, "Работа")]

    entry = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children[0]

    assert entry.label == "Работа"


def test_the_error_state_has_its_own_status_line():
    items = build_menu(ConnectionState.ERROR, [], profile_name="")

    assert items[0].label == "Статус: ошибка"


def test_the_error_state_offers_to_connect_again():
    items = build_menu(ConnectionState.ERROR, [], profile_name="")

    assert _find(items, "Подключить") is not None
