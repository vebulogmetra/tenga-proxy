"""Перевод дерева меню в варианты D-Bus."""

from __future__ import annotations

from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator
from src.ui.tray.variants import layout_variant, pack_properties, properties_variant


def test_a_string_property_becomes_a_string_variant():
    packed = pack_properties({"label": "Выход"})

    assert packed["label"].get_type_string() == "s"
    assert packed["label"].get_string() == "Выход"


def test_a_boolean_property_becomes_a_boolean_variant():
    packed = pack_properties({"enabled": False})

    assert packed["enabled"].get_type_string() == "b"
    assert packed["enabled"].get_boolean() is False


def test_an_integer_property_becomes_an_int32_variant():
    packed = pack_properties({"toggle-state": 1})

    assert packed["toggle-state"].get_type_string() == "i"


def test_layout_variant_has_the_signature_the_panel_expects():
    model = MenuModel([MenuItem("Выход")])

    variant = layout_variant(model, 0, revision=7)

    # Ровно та сигнатура, что отдаёт работающее приложение: (u(ia{sv}av)).
    assert variant.get_type_string() == "(u(ia{sv}av))"


def test_layout_variant_carries_the_revision():
    model = MenuModel([MenuItem("Выход")])

    assert layout_variant(model, 0, revision=7).unpack()[0] == 7


def test_layout_variant_unpacks_to_the_expected_tree():
    model = MenuModel([MenuItem("Подключить"), separator(), MenuItem("Выход")])

    _revision, root = layout_variant(model, 0, revision=1).unpack()
    root_id, root_props, children = root

    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child[1].get("label", "") for child in children] == ["Подключить", "", "Выход"]
    assert children[1][1]["type"] == "separator"


def test_layout_variant_nests_submenus():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A"), MenuItem("B")])])

    _revision, root = layout_variant(model, 0, revision=1).unpack()
    _child_id, _child_props, grandchildren = root[2][0]

    assert [item[1]["label"] for item in grandchildren] == ["A", "B"]


def test_layout_variant_of_an_unknown_parent_is_an_empty_tree():
    model = MenuModel([MenuItem("Выход")])

    _revision, root = layout_variant(model, 99, revision=1).unpack()

    # Панель не должна получить ошибку за несуществующий узел — ей отдаётся
    # пустое поддерево с тем же идентификатором.
    assert root == (99, {}, [])


def test_properties_variant_has_the_group_signature():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    variant = properties_variant(model, [1, 2], [])

    assert variant.get_type_string() == "(a(ia{sv}))"


def test_properties_variant_unpacks_to_id_and_properties():
    model = MenuModel([MenuItem("Первый")])

    (pairs,) = properties_variant(model, [1], []).unpack()

    assert pairs == [(1, {"enabled": True, "visible": True, "label": "Первый"})]
