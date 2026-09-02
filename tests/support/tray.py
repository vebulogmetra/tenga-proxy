"""Stand-ins used by the tray tests.

Заглушка живёт отдельно, потому что нужна и тестам контроллера, и тестам
приложения: копия в двух файлах разошлась бы при первой же правке.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeTrayItem:
    """Records what the controller told the tray item to do."""

    icons: list = field(default_factory=list)
    tooltips: list = field(default_factory=list)
    menus: list = field(default_factory=list)
    published: bool = False
    stopped: bool = False
    on_activate: object = None
    on_primary: object = None
    is_registered: bool = False

    def publish(self):
        self.published = True

    def shutdown(self):
        self.stopped = True

    def set_icon(self, name, theme_path=""):
        self.icons.append(name)

    def set_tooltip(self, text):
        self.tooltips.append(text)

    def set_menu(self, items):
        self.menus.append(items)

    def set_on_activate(self, handler):
        self.on_activate = handler

    def set_on_primary(self, handler):
        self.on_primary = handler


@dataclass
class FakeApp:
    """Records the actions the tray asks the application to run."""

    activated: list = field(default_factory=list)

    def activate_action(self, name, target=None):
        self.activated.append((name, target))


def find_item(items, label):
    """Find a menu entry by its label, descending into submenus."""
    for item in items:
        if item.label == label:
            return item
        found = find_item(item.children, label)
        if found is not None:
            return found
    return None


def labels(items):
    """Labels of a list of menu entries."""
    return [item.label for item in items]
