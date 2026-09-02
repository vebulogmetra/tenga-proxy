"""Subscriptions page: a list of subscription groups with update buttons."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.ui.logic.subscriptions_view import SubscriptionRow, build_subscription_rows


class SubscriptionsPage(Gtk.Box):
    """Search bar, subscription rows and the empty state."""

    __gtype_name__ = "TengaSubscriptionsPage"

    __gsignals__ = {
        "subscription-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "subscription-update": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._groups: Mapping[int, Any] = {}
        self._counts: Mapping[int, int] = {}
        self._query = ""
        self._rows: list[SubscriptionRow] = []
        self._row_widgets: dict[int, Adw.ActionRow] = {}
        self._update_buttons: dict[int, Gtk.Button] = {}

        self._build_search_bar()
        self._build_stack()
        self.refresh()

    def _build_search_bar(self) -> None:
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.set_placeholder_text("Название, адрес или дата обновления")
        self.search_entry.connect("search-changed", self._on_search_changed)

        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_child(self.search_entry)
        self.search_bar.connect_entry(self.search_entry)
        self.append(self.search_bar)

    def _build_stack(self) -> None:
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_vexpand(True)
        self.append(self._stack)

        self._empty_page = Adw.StatusPage(
            icon_name="folder-download-symbolic",
            title="Подписок пока нет",
            description="Добавьте подписку, чтобы профили обновлялись автоматически.",
        )
        self._stack.add_named(self._empty_page, "empty")

        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        self._list_page = Adw.PreferencesPage()
        self._group = Adw.PreferencesGroup()
        self._list_page.add(self._group)
        scrolled.set_child(self._list_page)
        self._stack.add_named(scrolled, "list")

    # --- модель ---

    def _rebuild(self) -> None:
        for widget in self._row_widgets.values():
            self._group.remove(widget)
        self._row_widgets.clear()
        self._update_buttons.clear()

        self._rows = build_subscription_rows(self._groups, self._counts, query=self._query)

        for row in self._rows:
            self._group.add(self._build_row(row))

        self._stack.set_visible_child_name("list" if self._rows else "empty")

    def _build_row(self, row: SubscriptionRow) -> Adw.ActionRow:
        action_row = Adw.ActionRow(title=row.name, subtitle=row.url)
        action_row.set_subtitle_lines(1)
        action_row.set_activatable(True)
        action_row.connect(
            "activated", lambda _row, gid=row.group_id: self.emit("subscription-activated", gid)
        )

        meta = Gtk.Label(label=f"{row.profile_count} · {row.updated_text}")
        meta.add_css_class("dim-label")
        meta.add_css_class("caption")
        action_row.add_suffix(meta)

        button = Gtk.Button(icon_name="view-refresh-symbolic")
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text("Обновить подписку")
        button.add_css_class("flat")
        button.connect(
            "clicked", lambda _b, gid=row.group_id: self.emit("subscription-update", gid)
        )
        action_row.add_suffix(button)

        self._row_widgets[row.group_id] = action_row
        self._update_buttons[row.group_id] = button
        return action_row

    # --- публичное api ---

    def set_data(self, groups: Mapping[int, Any], profile_counts: Mapping[int, int]) -> None:
        """Replace the underlying data and rebuild the list."""
        self._groups = groups
        self._counts = profile_counts
        self.refresh()

    def set_query(self, query: str) -> None:
        self._query = query
        self.refresh()

    def set_search_enabled(self, enabled: bool) -> None:
        self.search_bar.set_search_mode(enabled)
        if enabled:
            self.search_entry.grab_focus()

    def refresh(self) -> None:
        """Rebuild the list from the current data and filter."""
        self._rebuild()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.set_query(entry.get_text())

    # --- аксессоры для тестов ---

    def get_visible_state(self) -> str:
        return self._stack.get_visible_child_name()

    def get_row_count(self) -> int:
        return len(self._rows)

    def get_subtitles(self) -> list[str]:
        return [widget.get_subtitle() for widget in self._row_widgets.values()]

    def click_update_for_test(self, *, group_id: int) -> None:
        self._update_buttons[group_id].emit("clicked")

    def activate_row_for_test(self, *, group_id: int) -> None:
        self._row_widgets[group_id].emit("activated")
