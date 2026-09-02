"""Дерево пунктов меню трея: идентификаторы, свойства, поиск по id."""

from __future__ import annotations

import pytest

from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator


def test_root_children_get_sequential_ids():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    assert [item.id for item in model.root.children] == [1, 2]


def test_root_itself_has_id_zero():
    model = MenuModel([MenuItem("Первый")])

    assert model.root.id == 0


def test_nested_items_continue_the_same_numbering():
    model = MenuModel(
        [
            MenuItem("Профили", children=[MenuItem("A"), MenuItem("B")]),
            MenuItem("Выход"),
        ]
    )
    profiles = model.root.children[0]

    assert profiles.id == 1
    assert [item.id for item in profiles.children] == [2, 3]
    assert model.root.children[1].id == 4


def test_properties_of_a_plain_item():
    model = MenuModel([MenuItem("Подключить")])

    assert model.properties(1) == {"label": "Подключить", "enabled": True, "visible": True}


def test_a_disabled_item_reports_enabled_false():
    model = MenuModel([MenuItem("Статус: Отключено", enabled=False)])

    assert model.properties(1)["enabled"] is False


def test_a_separator_carries_the_type_property():
    model = MenuModel([separator()])

    assert model.properties(1) == {"type": "separator", "enabled": True, "visible": True}


def test_a_parent_declares_a_submenu():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    assert model.properties(1)["children-display"] == "submenu"


def test_a_checked_item_reports_a_radio_toggle():
    model = MenuModel([MenuItem("Профиль", checked=True)])
    props = model.properties(1)

    assert props["toggle-type"] == "radio"
    assert props["toggle-state"] == 1


def test_an_unchecked_toggle_reports_state_zero():
    model = MenuModel([MenuItem("Профиль", checked=False)])

    # checked=False — это «переключатель, который выключен», а не «пункт без
    # переключателя»: у второго checked=None.
    assert model.properties(1)["toggle-state"] == 0


def test_an_item_without_a_toggle_has_no_toggle_properties():
    props = MenuModel([MenuItem("Выход")]).properties(1)

    assert "toggle-type" not in props
    assert "toggle-state" not in props


def test_an_icon_name_is_reported_when_given():
    model = MenuModel([MenuItem("Настройки", icon_name="preferences-system-symbolic")])

    assert model.properties(1)["icon-name"] == "preferences-system-symbolic"


def test_properties_of_an_unknown_id_are_empty():
    assert MenuModel([MenuItem("Один")]).properties(99) == {}


def test_find_returns_the_item_with_that_id():
    child = MenuItem("Вложенный")
    model = MenuModel([MenuItem("Родитель", children=[child])])

    assert model.find(2) is child


def test_find_returns_none_for_an_unknown_id():
    assert MenuModel([MenuItem("Один")]).find(42) is None


def test_the_action_of_an_item_is_kept():
    model = MenuModel([MenuItem("Выход", action="app.quit")])

    assert model.find(1).action == "app.quit"


def test_the_target_of_an_item_is_kept():
    model = MenuModel([MenuItem("Профиль", action="app.select-profile", target=17)])

    assert model.find(1).target == 17


def test_layout_lists_the_children_of_the_requested_parent():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")]), MenuItem("Выход")])

    root_id, root_props, children = model.layout(0)

    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child[0] for child in children] == [1, 3]


def test_layout_of_a_leaf_has_no_children():
    model = MenuModel([MenuItem("Выход")])

    _id, _props, children = model.layout(1)

    assert children == []


def test_layout_depth_one_stops_before_grandchildren():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    _id, _props, children = model.layout(0, depth=1)
    _child_id, _child_props, grandchildren = children[0]

    # Глубина 1 — только прямые потомки: панель запрашивает подменю отдельно.
    assert grandchildren == []


def test_layout_depth_minus_one_returns_the_whole_tree():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    _id, _props, children = model.layout(0, depth=-1)
    _child_id, _child_props, grandchildren = children[0]

    assert [item[0] for item in grandchildren] == [2]


def test_layout_of_an_unknown_parent_is_none():
    assert MenuModel([MenuItem("Один")]).layout(99) is None


def test_group_properties_returns_a_pair_per_requested_id():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    result = model.group_properties([1, 2])

    assert [item_id for item_id, _props in result] == [1, 2]
    assert result[0][1]["label"] == "Первый"


def test_group_properties_with_no_ids_returns_every_item():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    # Пустой список означает «все пункты» — так его толкует спецификация.
    assert len(model.group_properties([])) == 3  # корень и два пункта


def test_group_properties_filters_by_the_requested_names():
    model = MenuModel([MenuItem("Первый")])

    result = model.group_properties([1], names=["label"])

    assert result[0][1] == {"label": "Первый"}


def test_group_properties_skips_unknown_ids():
    model = MenuModel([MenuItem("Первый")])

    assert model.group_properties([1, 99]) == [(1, model.properties(1))]


def test_a_hidden_item_reports_visible_false():
    model = MenuModel([MenuItem("Скрытый", visible=False)])

    assert model.properties(1)["visible"] is False


@pytest.mark.parametrize("depth", [0, 1, 5, -1])
def test_layout_never_raises_for_any_depth(depth):
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    assert model.layout(0, depth=depth) is not None
