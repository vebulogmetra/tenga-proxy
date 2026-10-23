"""Дерево `MenuModel` в виде операций для AppendMenuW.

Идентификатор пункта Win32 совпадает с id модели, поэтому выбранный пункт
находится тем же `MenuModel.find`, что и в dbusmenu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.ui.tray.dbusmenu import MenuItem, MenuModel


@dataclass(frozen=True)
class Entry:
    id: int
    label: str
    enabled: bool
    checked: bool


@dataclass(frozen=True)
class Separator:
    label: str = ""


@dataclass
class Popup:
    label: str
    children: list = field(default_factory=list)


def win32_label(text: str) -> str:
    """`&` в Win32 — признак мнемоники; буквальный амперсанд удваивается."""
    return text.replace("&", "&&")


def _convert(items: list[MenuItem]) -> list:
    ops = []
    for item in items:
        if not item.visible:
            continue
        if item.is_separator:
            ops.append(Separator())
        elif item.children:
            ops.append(Popup(label=win32_label(item.label), children=_convert(item.children)))
        else:
            ops.append(
                Entry(
                    id=item.id,
                    label=win32_label(item.label),
                    enabled=item.enabled,
                    checked=bool(item.checked),
                )
            )
    return ops


def menu_ops(model: MenuModel) -> list:
    return _convert(model.root.children)
