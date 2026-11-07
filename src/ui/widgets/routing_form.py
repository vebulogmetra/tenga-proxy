"""Форма маршрутизации: режим, порядок, готовые правила, четыре списка.

Одна и та же форма — в настройках приложения (общие правила) и в диалоге
сервера (свои правила). Значения ходят через `src/ui/logic/routing_form.py`.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from src.db.config import RoutingMode
from src.ui.dialogs.settings import KeyedCombo
from src.ui.logic.routing_form import (
    LISTS,
    ORDER_LABELS,
    ORDER_PRESETS,
    FormValues,
    apply_form_values,
    current_catalog,
    form_values,
    order_key,
    ru_direct_subtitle,
)


def _list_view(title: str, subtitle: str) -> tuple[Adw.PreferencesGroup, Gtk.TextView]:
    """Build a titled text area for one routing list."""
    group = Adw.PreferencesGroup(title=title, description=subtitle)

    view = Gtk.TextView()
    view.set_monospace(True)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.set_left_margin(8)
    view.set_right_margin(8)

    scrolled = Gtk.ScrolledWindow(min_content_height=120)
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_child(view)
    scrolled.add_css_class("card")

    group.add(scrolled)
    return group, view


def _read(view: Gtk.TextView) -> str:
    buffer = view.get_buffer()
    start, end = buffer.get_bounds()
    return buffer.get_text(start, end, True)


class RoutingForm:
    """Группы формы, добавленные на `Adw.PreferencesPage`."""

    def __init__(self, page: Adw.PreferencesPage, *, vpn_hint: str | None = None) -> None:
        self.groups: list[Adw.PreferencesGroup] = []
        self._enabled = True

        mode_group = Adw.PreferencesGroup(title="Режим")
        page.add(mode_group)
        self.groups.append(mode_group)

        self._mode = KeyedCombo("Правила", RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_row = self._mode.row
        self.mode_row.connect("notify::selected", lambda *_: self._sync_mode())
        mode_group.add(self.mode_row)

        self._order = KeyedCombo("Приоритет групп", list(ORDER_PRESETS.keys()), ORDER_LABELS)
        self.order_row = self._order.row
        mode_group.add(self.order_row)

        self.bypass_row = Adw.SwitchRow(
            title="Локальные сети напрямую",
            subtitle="127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
        )
        mode_group.add(self.bypass_row)

        self.ru_direct_row = Adw.SwitchRow(
            title="Российские сайты и IP напрямую",
            subtitle=ru_direct_subtitle(current_catalog()),
        )
        mode_group.add(self.ru_direct_row)

        self.views: dict[str, Gtk.TextView] = {}
        for key, title, hint in LISTS:
            if key == "vpn" and vpn_hint is not None:
                hint = vpn_hint
            group, view = _list_view(title, hint)
            page.add(group)
            self.groups.append(group)
            self.views[key] = view

    # --- состояние ---

    def _sync_mode(self) -> None:
        # В режиме «весь трафик через прокси» списки не применяются: активными
        # они обещали бы несуществующий эффект. «Локальные сети» действуют всегда.
        custom = self._enabled and self._mode.selected() == RoutingMode.CUSTOM
        for widget in (*self.views.values(), self.order_row, self.ru_direct_row):
            widget.set_sensitive(custom)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.mode_row.set_sensitive(enabled)
        self.bypass_row.set_sensitive(enabled)
        self._sync_mode()

    def load(self, routing) -> None:
        values = form_values(routing)
        self._mode.select(values.mode)
        self._order.select(values.order)
        self.bypass_row.set_active(values.bypass_local_networks)
        self.ru_direct_row.set_active(values.ru_direct)
        for key, text in values.lists.items():
            self.set_text(key, text)
        self._sync_mode()

    def values(self) -> FormValues:
        return FormValues(
            mode=self._mode.selected(),
            order=self._order.selected(),
            bypass_local_networks=self.bypass_row.get_active(),
            ru_direct=self.ru_direct_row.get_active(),
            lists={key: _read(view) for key, view in self.views.items()},
        )

    def read(self, routing) -> None:
        """Записать форму в `routing`; негодная запись — ValueError, цель не тронута."""
        apply_form_values(routing, self.values())

    def connect_changed(self, callback: Callable[[], None]) -> None:
        for row in (self.mode_row, self.order_row):
            row.connect("notify::selected", lambda *_: callback())
        for row in (self.bypass_row, self.ru_direct_row):
            row.connect("notify::active", lambda *_: callback())
        for view in self.views.values():
            view.get_buffer().connect("changed", lambda *_: callback())

    # --- доступ к полям ---

    def select_mode(self, key: str) -> None:
        self._mode.select(key)
        self._sync_mode()

    def selected_mode(self) -> str:
        return self._mode.selected()

    def select_order(self, order: list[str]) -> None:
        self._order.select(order_key(order))

    def selected_order(self) -> list[str]:
        return list(ORDER_PRESETS[self._order.selected()])

    def text(self, key: str) -> str:
        return _read(self.views[key])

    def set_text(self, key: str, text: str) -> None:
        self.views[key].get_buffer().set_text(text)
