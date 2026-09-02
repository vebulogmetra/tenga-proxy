"""Menu tree for com.canonical.dbusmenu.

Модуль не импортирует ни GTK, ни Gio: дерево и его свойства — обычные Python-
объекты, поэтому проверяются без шины и без дисплея. Превращением в
`GLib.Variant` занимается `variants.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Идентификатор корня зафиксирован спецификацией: панель всегда запрашивает
# раскладку начиная с нуля.
ROOT_ID = 0


@dataclass
class MenuItem:
    """One entry of the tray menu."""

    label: str = ""
    action: str = ""
    target: int | None = None
    enabled: bool = True
    visible: bool = True
    checked: bool | None = None
    icon_name: str = ""
    is_separator: bool = False
    children: list[MenuItem] = field(default_factory=list)
    id: int = -1


def separator() -> MenuItem:
    """A horizontal rule between groups of entries."""
    return MenuItem(is_separator=True)


class MenuModel:
    """A tree of `MenuItem` addressed by the integer ids dbusmenu uses."""

    def __init__(self, items: list[MenuItem]) -> None:
        self.root = MenuItem(children=list(items), id=ROOT_ID)
        self._by_id: dict[int, MenuItem] = {ROOT_ID: self.root}
        self._number(self.root.children, start=ROOT_ID + 1)

    def _number(self, items: list[MenuItem], start: int) -> int:
        """Give every item a unique id, depth first."""
        next_id = start
        for item in items:
            item.id = next_id
            self._by_id[next_id] = item
            next_id = self._number(item.children, next_id + 1)
        return next_id

    def find(self, item_id: int) -> MenuItem | None:
        """Return the item with that id, or None."""
        return self._by_id.get(item_id)

    def properties(self, item_id: int) -> dict:
        """Describe one item the way dbusmenu expects it."""
        item = self._by_id.get(item_id)
        if item is None:
            return {}

        props: dict = {"enabled": item.enabled, "visible": item.visible}

        if item.is_separator:
            props["type"] = "separator"
            return props

        props["label"] = item.label

        if item.children:
            props["children-display"] = "submenu"

        if item.checked is not None:
            # radio, а не checkmark: активен ровно один профиль, и панель
            # рисует такой набор как переключатель с единственным выбором.
            props["toggle-type"] = "radio"
            props["toggle-state"] = 1 if item.checked else 0

        if item.icon_name:
            props["icon-name"] = item.icon_name

        return props

    def layout(self, parent_id: int, depth: int = -1) -> tuple | None:
        """Build the nested (id, props, children) triple for one subtree."""
        item = self._by_id.get(parent_id)
        if item is None:
            return None
        return self._layout_of(item, depth)

    def _layout_of(self, item: MenuItem, depth: int) -> tuple:
        if depth == 0:
            children: list = []
        else:
            children = [self._layout_of(child, depth - 1) for child in item.children]
        return (item.id, self.properties(item.id), children)

    def group_properties(self, ids: list[int], names: list[str] | None = None) -> list[tuple]:
        """Return (id, props) for the requested ids; an empty list means all."""
        wanted = ids or list(self._by_id)
        result = []
        for item_id in wanted:
            if item_id not in self._by_id:
                continue
            props = self.properties(item_id)
            if names:
                props = {k: v for k, v in props.items() if k in names}
            result.append((item_id, props))
        return result
