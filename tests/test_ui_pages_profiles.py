"""Widget tests for the profiles page (GTK4)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.gtk


@dataclass
class FakeGroup:
    id: int
    name: str
    is_subscription: bool = False
    subscription_url: str = ""
    last_updated: int = 0
    sub_user_info: str = ""
    sub_support_url: str = ""
    sub_web_page_url: str = ""
    sub_announce: str = ""
    sub_empty: bool = False
    sub_via_fallback: bool = False


@dataclass
class FakeBean:
    display_address: str


@dataclass
class FakeProfile:
    id: int
    name: str
    proxy_type: str
    bean: FakeBean
    latency_ms: int = -1


@pytest.fixture
def page(gtk_ready):
    from src.ui.pages.profiles import ProfilesPage

    return ProfilesPage()


@pytest.fixture
def data():
    groups = {
        1: FakeGroup(id=1, name="Работа"),
        2: FakeGroup(id=2, name="Подписка", is_subscription=True),
    }
    profiles = {
        1: [
            FakeProfile(1, "Альфа", "vless", FakeBean("alfa.example:443"), 120),
            FakeProfile(2, "Бета", "trojan", FakeBean("beta.example:8443"), 30),
        ],
        2: [FakeProfile(3, "Гамма", "vmess", FakeBean("gamma.example:80"))],
    }
    return groups, profiles


def test_page_builds(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Widget)


def test_empty_store_shows_the_status_page(page):
    page.set_data({}, {})
    assert page.get_visible_state() == "empty"


def test_non_empty_store_shows_the_list(page, data):
    page.set_data(*data)
    assert page.get_visible_state() == "list"


def test_every_group_becomes_a_root_row(page, data):
    page.set_data(*data)
    assert page.get_root_count() == 2


def test_filter_narrows_the_tree(page, data):
    page.set_data(*data)
    page.set_query("альфа")
    assert page.get_root_count() == 1


def test_filter_without_matches_shows_the_status_page(page, data):
    page.set_data(*data)
    page.set_query("такого сервера нет")
    assert page.get_visible_state() == "empty"


def test_expanding_a_group_reveals_its_profiles(page, data):
    page.set_data(*data)
    page.expand_all()
    # Две группы плюс три профиля.
    assert page.get_visible_row_count() == 5


def test_profile_activated_carries_the_id(page, data):
    received: list[int] = []
    page.connect("profile-activated", lambda _page, profile_id: received.append(profile_id))

    page.set_data(*data)
    page.expand_all()
    page.emit_activation_for_test(profile_id=2)

    assert received == [2]


def test_group_rows_do_not_emit_activation(page, data):
    received: list[int] = []
    page.connect("profile-activated", lambda _page, profile_id: received.append(profile_id))

    page.set_data(*data)
    page.activate_row_for_test(0)

    assert received == []


def test_sorting_by_ping_reorders_profiles(page, data):
    from src.ui.logic.profiles_view import SortKey

    page.set_data(*data)
    page.set_sort(SortKey.PING, ascending=True)
    rows = page.get_profile_titles(group_id=1)
    assert rows == ["Бета", "Альфа"]


def test_active_profile_is_flagged(page, data):
    page.set_active_profile(3)
    page.set_data(*data)
    assert page.get_active_titles() == ["Гамма"]


def test_a_context_click_on_a_profile_reports_it(page, data):
    page.set_data(*data)
    page.expand_all()
    seen: list[tuple[int, bool]] = []
    page.connect(
        "profile-context",
        lambda _p, item_id, is_group: seen.append((item_id, is_group)),
    )

    # Позиция 1 — первый ребёнок первой группы: группы идут по алфавиту,
    # «Подписка» раньше «Работы».
    page.emit_context_for_test(position=1)

    assert seen == [(3, False)]


def test_a_context_click_on_a_group_reports_the_group(page, data):
    page.set_data(*data)
    seen: list[tuple[int, bool]] = []
    page.connect(
        "profile-context",
        lambda _p, item_id, is_group: seen.append((item_id, is_group)),
    )

    page.emit_context_for_test(position=0)

    assert seen == [(2, True)]


def test_a_context_click_moves_the_selection(page, data):
    """Пункты меню работают с выделением — щелчок должен его перенести."""
    page.set_data(*data)
    page.expand_all()

    page.emit_context_for_test(position=2)

    assert page.get_selected_position() == 2


def test_a_context_click_past_the_last_row_is_ignored(page, data):
    page.set_data(*data)
    seen: list[int] = []
    page.connect("profile-context", lambda _p, item_id, _g: seen.append(item_id))

    page.emit_context_for_test(position=99)

    assert seen == []


def test_the_context_menu_of_a_profile_offers_connecting(page, data):
    page.set_data(*data)
    page.expand_all()

    labels = page.context_menu_labels_for_test(position=1)

    assert "Подключить" in labels
    assert "VPN и маршруты…" in labels


def test_the_context_menu_of_a_group_offers_expanding(page, data):
    page.set_data(*data)

    labels = page.context_menu_labels_for_test(position=0)

    assert "Развернуть группу" in labels
    assert "Подключить" not in labels


def test_an_expanded_group_offers_collapsing(page, data):
    page.set_data(*data)
    page.expand_all()

    assert "Свернуть группу" in page.context_menu_labels_for_test(position=0)


def test_context_menu_points_at_click(page, data, monkeypatch):
    """Меню должно всплывать в точке клика, а не в углу списка.

    Gdk.Rectangle игнорирует аргументы конструктора: прямоугольник,
    собранный как Rectangle(x=..., y=...), остаётся нулевым, и popover
    прилипает к верхнему левому углу.
    """
    groups, profiles = data
    page.set_data(groups, profiles)

    captured = {}

    def fake_set_pointing_to(rect):
        captured["x"] = rect.x
        captured["y"] = rect.y

    monkeypatch.setattr(page._menu_popover, "set_pointing_to", fake_set_pointing_to)
    monkeypatch.setattr(page.list_view, "get_realized", lambda: True)
    monkeypatch.setattr(page._menu_popover, "popup", lambda: None)

    page._open_context_menu(0, 137.0, 208.0)

    assert (captured.get("x"), captured.get("y")) == (137, 208)


def test_refresh_keeps_groups_expanded(page, data):
    """Обновление списка не должно схлопывать раскрытые группы.

    Пинг группы перерисовывает страницу на каждую порцию результатов:
    если раскрытие теряется, строки схлопываются прямо во время замера.
    """
    groups, profiles = data
    page.set_data(groups, profiles)
    page.expand_all()
    assert page.get_visible_row_count() == 5

    page.refresh()

    assert page.get_visible_row_count() == 5


def test_refresh_keeps_a_collapsed_group_collapsed(page, data):
    """Свёрнутая группа не должна раскрываться сама по себе."""
    groups, profiles = data
    page.set_data(groups, profiles)
    page.expand_all()
    page.toggle_group(1)
    collapsed = page.get_visible_row_count()

    page.refresh()

    assert page.get_visible_row_count() == collapsed


def test_refresh_keeps_the_selected_profile(page, data):
    """Выделенный профиль переживает пересборку списка.

    Отключение перерисовывает страницу, и без переноса выделение уходило на
    группу: «Подключить» после этого просил выбрать профиль заново.
    """
    page.set_data(*data)
    page.expand_all()
    page.select_profile(2)
    assert page.get_selected_profile_id() == 2

    page.set_active_profile(2)
    page.set_active_profile(-1)

    assert page.get_selected_profile_id() == 2


def test_select_profile_ignores_a_hidden_profile(page, data):
    page.set_data(*data)
    assert page.select_profile(3) is False


def _drain_events() -> None:
    from gi.repository import GLib

    context = GLib.MainContext.default()
    for _ in range(200):
        if not context.pending():
            break
        context.iteration(False)


def _many_profiles(count: int = 80):
    groups = {1: FakeGroup(id=1, name="Большая")}
    profiles = {
        1: [
            FakeProfile(i, f"П{i:03d}", "vless", FakeBean(f"h{i}.example:443"))
            for i in range(count)
        ]
    }
    return groups, profiles


def test_refresh_keeps_the_scroll_position(page):
    """Обновление списка не должно перематывать его наверх.

    Список перестраивают подключение, замер задержки и обновление подписок:
    если перерисовка сбрасывает прокрутку, список невозможно листать.
    """
    from gi.repository import Gtk

    groups, profiles = _many_profiles()
    page.set_data(groups, profiles)
    page.expand_all()

    # Прокрутка ограничена размером виджета: без окна высота нулевая и
    # adjustment всегда остаётся в нуле.
    window = Gtk.Window(default_width=600, default_height=400)
    window.set_child(page)
    window.present()

    adjustment = page.get_vadjustment_for_test()
    # Разметка доезжает не за один проход, а под нагрузкой всего набора
    # тестов — тем более: ждём, пока список получит высоту.
    before = 0.0
    for _ in range(50):
        _drain_events()
        adjustment.set_value(400.0)
        before = adjustment.get_value()
        if before > 0:
            break

    if before <= 0:
        window.set_child(None)
        window.destroy()
        pytest.skip("Список не получил высоту: прокрутку проверить нельзя")

    page.refresh()
    _drain_events()

    assert page.get_vadjustment_for_test().get_value() == before

    window.set_child(None)
    window.destroy()


def _present(page):
    from gi.repository import Gtk

    window = Gtk.Window(default_width=600, default_height=400)
    window.set_child(page)
    window.present()
    for _ in range(50):
        _drain_events()
        if page.group_progress_for_test(1) is not None or page._group_cells:
            break
    return window


def test_group_shows_the_progress_of_a_ping(page, data):
    from src.ui.logic.latency import PingProgress

    page.set_data(*data)
    window = _present(page)
    if not page._group_cells:
        window.destroy()
        pytest.skip("Строки не отрисовались: ячейки групп проверить нельзя")

    progress = PingProgress({1: [1, 2]})
    page.set_ping_progress(progress)
    assert page.group_progress_for_test(1) == ("0 / 2", 0.0)
    assert page.group_progress_for_test(2) is None

    progress.record(1)
    page.update_group_progress(1)
    assert page.group_progress_for_test(1) == ("1 / 2", 0.5)

    page.set_ping_progress(None)
    assert page.group_progress_for_test(1) is None

    window.set_child(None)
    window.destroy()


def test_a_rebuild_keeps_the_progress_of_a_ping(page, data):
    from src.ui.logic.latency import PingProgress

    page.set_data(*data)
    window = _present(page)
    if not page._group_cells:
        window.destroy()
        pytest.skip("Строки не отрисовались: ячейки групп проверить нельзя")

    progress = PingProgress({1: [1, 2]})
    progress.record(2)
    page.set_ping_progress(progress)
    page.refresh()
    _drain_events()

    assert page.group_progress_for_test(1) == ("1 / 2", 0.5)

    window.set_child(None)
    window.destroy()


# --- двухстрочный список, инструменты и строка выделения -------------------


def test_tree_is_a_list_view_with_two_line_rows(page):
    from gi.repository import Gtk

    assert isinstance(page.list_view, Gtk.ListView)
    assert not hasattr(page, "column_view")


def _present_rows(page):
    window = Gtk_window(page)
    for _ in range(50):
        _drain_events()
        if page._profile_cells:
            break
    return window


def Gtk_window(page):
    from gi.repository import Gtk

    window = Gtk.Window(default_width=900, default_height=600)
    window.set_child(page)
    window.present()
    return window


def _close(window):
    window.set_child(None)
    window.destroy()


def test_profile_row_shows_type_address_latency_and_badge(page, data):
    page.set_active_profile(2)
    page.set_data(*data)
    page.expand_all()
    window = _present_rows(page)
    if page.row_widget_for_test(profile_id=2) is None:
        _close(window)
        pytest.skip("Строки не отрисовались")

    row = page.row_widget_for_test(profile_id=2)
    assert row.get_title() == "Бета"
    assert row.get_details() == "TROJAN · beta.example:8443"
    assert row.get_latency() == "30 мс"
    assert row.get_badge() == "Подключён"
    assert "profile-active" in row.get_css_classes()

    other = page.row_widget_for_test(profile_id=1)
    assert other.get_badge() == ""
    assert other.get_latency() == "120 мс"
    assert "profile-active" not in other.get_css_classes()
    _close(window)


def test_ping_button_tests_only_its_server(page, data):
    page.set_data(*data)
    page.expand_all()
    window = _present_rows(page)
    if page.row_widget_for_test(profile_id=1) is None:
        _close(window)
        pytest.skip("Строки не отрисовались")
    seen = []
    page.connect("profile-ping", lambda _p, pid: seen.append(pid))

    page.row_widget_for_test(profile_id=1).ping_button.emit("clicked")
    assert seen == [1]
    _close(window)


def test_menu_button_opens_the_same_context_menu(page, data):
    page.set_data(*data)
    page.expand_all()
    window = _present_rows(page)
    if page.row_widget_for_test(profile_id=1) is None:
        _close(window)
        pytest.skip("Строки не отрисовались")
    seen = []
    page.connect("profile-context", lambda _p, item_id, is_group: seen.append((item_id, is_group)))

    row = page.row_widget_for_test(profile_id=1)
    assert row.menu_button.get_tooltip_text() == "Действия"
    row.menu_button.emit("clicked")
    assert seen == [(1, False)]
    assert page.get_selected_profile_id() == 1
    assert page.context_menu_labels_for_test(profile_id=1) == [
        "Подключить",
        "VPN и маршруты…",
        "Тест задержки",
        "Редактировать",
        "Удалить",
    ]
    _close(window)


def test_group_row_summary_and_progress(page, data):
    from src.ui.logic.latency import PingProgress

    page.set_data(*data)
    window = _present_rows(page)
    group = page.row_widget_for_test(group_id=1)
    if group is None:
        _close(window)
        pytest.skip("Строки не отрисовались")
    assert group.get_title() == "Работа"
    assert group.get_summary() == "Серверов: 2"

    progress = PingProgress({1: [1, 2]})
    progress.record(1)
    page.set_ping_progress(progress)
    assert group.get_summary() == "Серверов: 2  ·  Проверено: 1 / 2"
    assert group.progress.get_visible() is True
    _close(window)


def test_search_entry_is_always_visible(page):
    from src.ui.logic.profiles_view import SEARCH_PLACEHOLDER

    assert not hasattr(page, "search_bar")
    assert page.search_entry.get_visible() is True
    assert page.search_entry.get_placeholder_text() == SEARCH_PLACEHOLDER


def test_tools_row_has_add_and_sort_menus(page):
    from src.ui.logic.menus import ADD_MENU

    assert page.add_button.get_label() == "Добавить…"
    assert page.menu_labels_for_test(page.add_button) == [label for _n, label in ADD_MENU]
    assert page.sort_button.get_label() == "Сортировка"
    assert page.menu_labels_for_test(page.sort_button) == ["По имени", "По типу", "По задержке"]


def test_choosing_the_same_sort_key_flips_the_direction(page, data):
    from src.ui.logic.profiles_view import SortKey

    page.set_data(*data)
    assert page.get_sort_for_test() == (SortKey.NAME, True)
    page.activate_sort_for_test("type")
    assert page.get_sort_for_test() == (SortKey.TYPE, True)
    page.activate_sort_for_test("type")
    assert page.get_sort_for_test() == (SortKey.TYPE, False)
    page.activate_sort_for_test("name")
    assert page.get_sort_for_test() == (SortKey.NAME, True)


def test_no_results_text_when_search_matches_nothing(page, data):
    from src.ui.logic.profiles_view import EMPTY_TITLE, NO_RESULTS_TEXT

    page.set_data(*data)
    page.set_query("нет такого")
    assert page.get_visible_state() == "empty"
    assert page.get_empty_title() == NO_RESULTS_TEXT

    page.set_query("")
    page.set_data({}, {})
    assert page.get_empty_title() == EMPTY_TITLE


def test_selection_row_names_the_target_and_offers_the_switch(page, data):
    from src.ui.logic.profiles_view import SELECTED_NONE
    from src.ui.logic.status import SWITCH_LABEL

    page.set_data(*data)
    assert page.get_selection_text() == SELECTED_NONE
    assert page.switch_button.get_visible() is False

    page.expand_all()
    page.select_profile(1)
    assert page.get_selection_text() == "Выбран: Альфа"

    page.set_switch_target("Альфа", enabled=True)
    assert page.switch_button.get_visible() is True
    assert page.switch_button.get_label() == SWITCH_LABEL
    assert page.switch_button.get_tooltip_text() == "Подключить: Альфа"

    page.set_switch_target("", enabled=True)
    assert page.switch_button.get_visible() is False


def test_switch_button_emits_its_own_signal(page):
    seen = []
    page.connect("switch-clicked", lambda _page: seen.append(True))
    page.set_switch_target("Альфа", enabled=True)
    page.switch_button.emit("clicked")
    assert seen == [True]


def test_subscription_group_menu_offers_an_update(page, data):
    page.set_data(*data)
    assert page.context_menu_labels_for_test(group_id=2) == [
        "Развернуть группу",
        "Обновить подписку",
        "Тест задержки",
        "Оставить рабочие…",
        "Редактировать",
        "Удалить",
    ]
    assert "Обновить подписку" not in page.context_menu_labels_for_test(group_id=1)
