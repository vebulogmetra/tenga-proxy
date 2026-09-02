"""Turn the menu tree into the GLib variants dbusmenu speaks.

Вынесено из `sni.py`: сборка рекурсивного `av` требует `VariantBuilder` и
`new_variant` на каждом уровне — оверрайд PyGObject не умеет собирать такой тип
из вложенных кортежей. Отдельный модуль позволяет проверить форму без шины.
"""

from __future__ import annotations

from gi.repository import GLib

from src.ui.tray.dbusmenu import MenuModel

ITEM_TYPE = GLib.VariantType.new("(ia{sv}av)")
AV_TYPE = GLib.VariantType.new("av")
LAYOUT_TYPE = GLib.VariantType.new("(u(ia{sv}av))")
PAIR_TYPE = GLib.VariantType.new("(ia{sv})")
PAIRS_TYPE = GLib.VariantType.new("a(ia{sv})")
GROUP_TYPE = GLib.VariantType.new("(a(ia{sv}))")


def pack_properties(props: dict) -> dict:
    """Wrap plain Python values into the variants a{sv} needs."""
    packed = {}
    for key, value in props.items():
        # bool раньше int: в Python bool наследуется от int, и порядок проверок
        # решает, каким типом уедет на шину.
        if isinstance(value, bool):
            packed[key] = GLib.Variant("b", value)
        elif isinstance(value, int):
            packed[key] = GLib.Variant("i", value)
        else:
            packed[key] = GLib.Variant("s", str(value))
    return packed


def _item_variant(node: tuple) -> GLib.Variant:
    """Build one (ia{sv}av) node, recursing into its children."""
    item_id, props, children = node

    builder = GLib.VariantBuilder.new(ITEM_TYPE)
    builder.add_value(GLib.Variant("i", item_id))
    builder.add_value(GLib.Variant("a{sv}", pack_properties(props)))

    kids = GLib.VariantBuilder.new(AV_TYPE)
    for child in children:
        # new_variant, а не GLib.Variant("v", …): второй вариант в PyGObject
        # принимает только простые значения и падает на готовом Variant.
        kids.add_value(GLib.Variant.new_variant(_item_variant(child)))
    builder.add_value(kids.end())

    return builder.end()


def layout_variant(model: MenuModel, parent_id: int, revision: int, depth: int = -1):
    """Build the reply of com.canonical.dbusmenu.GetLayout."""
    node = model.layout(parent_id, depth=depth)
    if node is None:
        # Панель не должна получить ошибку за несуществующий узел: она могла
        # запросить пункт, исчезнувший при перестроении меню.
        node = (parent_id, {}, [])

    builder = GLib.VariantBuilder.new(LAYOUT_TYPE)
    builder.add_value(GLib.Variant("u", revision))
    builder.add_value(_item_variant(node))
    return builder.end()


def _pair_variant(item_id: int, props: dict) -> GLib.Variant:
    """Build one (ia{sv}) pair.

    Через builder по той же причине, что и узлы дерева: в кортеж со словарём
    готовых Variant оверрайд PyGObject не умеет.
    """
    builder = GLib.VariantBuilder.new(PAIR_TYPE)
    builder.add_value(GLib.Variant("i", item_id))
    builder.add_value(GLib.Variant("a{sv}", pack_properties(props)))
    return builder.end()


def properties_variant(model: MenuModel, ids: list[int], names: list[str]):
    """Build the reply of com.canonical.dbusmenu.GetGroupProperties."""
    pairs = GLib.VariantBuilder.new(PAIRS_TYPE)
    for item_id, props in model.group_properties(ids, names):
        pairs.add_value(_pair_variant(item_id, props))

    builder = GLib.VariantBuilder.new(GROUP_TYPE)
    builder.add_value(pairs.end())
    return builder.end()
