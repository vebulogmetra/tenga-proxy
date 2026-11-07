"""Subscription list of the settings section «Подписки»: rows, menus and buttons."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from src.ui.logic.subscriptions_view import (
    EMPTY_RESPONSE_HINT,
    EMPTY_RESPONSE_TEXT,
    VIA_FALLBACK_TEXT,
    SubscriptionRow,
    build_subscription_rows,
)

EMPTY_TEXT = "Подписок нет. Добавьте ссылку от провайдера."
SELECTED_CLASS = "subscription-selected"
BUTTONS = (
    ("Добавить…", "app.add-subscription", False),
    ("Обновить", "win.update-subscription", True),
    ("Изменить…", "win.edit-subscription", True),
    ("Удалить", "win.delete-subscription", True),
)


class SubscriptionsList(Adw.PreferencesGroup):
    """Subscription rows with their menus; buttons below act on the selected row."""

    __gtype_name__ = "TengaSubscriptionsList"

    def __init__(self) -> None:
        super().__init__(title="Подписки")

        self._groups: Mapping[int, Any] = {}
        self._counts: Mapping[int, int] = {}
        self._rows: list[SubscriptionRow] = []
        self._selected = -1
        self._row_widgets: dict[int, Adw.ActionRow] = {}
        self._update_buttons: dict[int, Gtk.Button] = {}
        self._menu_buttons: dict[int, Gtk.MenuButton] = {}
        self._details_labels: dict[int, Gtk.Label] = {}
        self._announce_labels: dict[int, Gtk.Label] = {}
        self._empty_labels: dict[int, Gtk.Label] = {}
        self._via_fallback_labels: dict[int, Gtk.Label] = {}

        self._empty_row = Adw.ActionRow(title=EMPTY_TEXT)
        self._empty_row.add_css_class("dim-label")
        self.add(self._empty_row)

        # Кнопки под списком, как в Qt; цель — выделенная строка.
        buttons = Gtk.Box(spacing=8, margin_top=12, halign=Gtk.Align.START)
        self.buttons: list[Gtk.Button] = []
        for label, action, _needs_target in BUTTONS:
            button = Gtk.Button(label=label)
            if action.startswith("app."):
                button.set_action_name(action)
            buttons.append(button)
            self.buttons.append(button)
        self.add(buttons)
        self.refresh()

    # --- модель ---

    def _rebuild(self) -> None:
        for widget in self._row_widgets.values():
            self.remove(widget)
        self._row_widgets.clear()
        self._update_buttons.clear()
        self._menu_buttons.clear()
        self._details_labels.clear()
        self._announce_labels.clear()
        self._empty_labels.clear()
        self._via_fallback_labels.clear()

        self._rows = build_subscription_rows(self._groups, self._counts)

        # Строки идут перед кнопками: `add` кладёт строки в общий список
        # группы, а остальные виджеты — под ним.
        for row in self._rows:
            self.add(self._build_row(row))
        self._empty_row.set_visible(not self._rows)

        ids = [row.group_id for row in self._rows]
        self._select(self._selected if self._selected in ids else (ids[0] if ids else -1))

    def _build_row(self, row: SubscriptionRow) -> Adw.ActionRow:
        # Имя и адрес приходят извне: амперсанд в query не является разметкой.
        action_row = Adw.ActionRow()
        action_row.set_use_markup(False)
        action_row.set_title(row.name)
        action_row.set_subtitle(row.url)
        action_row.set_subtitle_lines(1)
        action_row.set_activatable(True)
        action_row.connect("activated", lambda _row, gid=row.group_id: self._select(gid))

        if row.announce:
            action_row.add_suffix(self._build_announce_button(row))

        meta_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        meta = Gtk.Label(label=f"{row.profile_count} · {row.updated_text}", xalign=1.0)
        meta.add_css_class("dim-label")
        meta.add_css_class("caption")
        meta_box.append(meta)
        if row.details_text:
            details = Gtk.Label(label=row.details_text, xalign=1.0)
            details.add_css_class("caption")
            # Истёкшую подписку видно сразу: серверов в ней обычно уже нет.
            details.add_css_class("error" if row.expired else "dim-label")
            meta_box.append(details)
            self._details_labels[row.group_id] = details
        if row.empty:
            # Без пометки сохранённые серверы выглядели бы рабочими.
            empty = Gtk.Label(label=EMPTY_RESPONSE_TEXT, xalign=1.0)
            empty.add_css_class("caption")
            empty.add_css_class("error")
            empty.set_tooltip_text(EMPTY_RESPONSE_HINT)
            meta_box.append(empty)
            self._empty_labels[row.group_id] = empty
        if row.via_fallback:
            via_fallback = Gtk.Label(label=VIA_FALLBACK_TEXT, xalign=1.0)
            via_fallback.add_css_class("caption")
            via_fallback.add_css_class("dim-label")
            meta_box.append(via_fallback)
            self._via_fallback_labels[row.group_id] = via_fallback
        action_row.add_suffix(meta_box)

        button = Gtk.Button(icon_name="view-refresh-symbolic")
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text("Обновить подписку")
        button.add_css_class("flat")
        # Действие окна, как у пунктов меню: диалог настроек живёт внутри окна.
        button.set_action_name("win.update-subscription")
        button.set_action_target_value(GLib.Variant.new_int32(row.group_id))
        action_row.add_suffix(button)

        menu_button = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_button.set_valign(Gtk.Align.CENTER)
        menu_button.set_tooltip_text("Действия")
        menu_button.add_css_class("flat")
        menu_button.set_menu_model(self._menu_model_for(row))
        action_row.add_suffix(menu_button)

        self._row_widgets[row.group_id] = action_row
        self._update_buttons[row.group_id] = button
        self._menu_buttons[row.group_id] = menu_button
        return action_row

    def _build_announce_button(self, row: SubscriptionRow) -> Gtk.MenuButton:
        """A button revealing the provider's announcement in a popover."""
        # Обычная метка, не разметка: текст объявления пишет провайдер.
        label = Gtk.Label(label=row.announce, wrap=True, max_width_chars=40, xalign=0.0)
        label.set_selectable(True)
        for side in ("top", "bottom", "start", "end"):
            getattr(label, f"set_margin_{side}")(6)

        popover = Gtk.Popover()
        popover.set_child(label)

        button = Gtk.MenuButton(icon_name="dialog-information-symbolic")
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text("Объявление провайдера")
        button.add_css_class("flat")
        button.set_popover(popover)

        self._announce_labels[row.group_id] = label
        return button

    @staticmethod
    def _menu_model_for(row: SubscriptionRow) -> Gio.Menu:
        """Build the menu of one subscription row.

        Идентификатор группы вшит в каждое действие: у строк общий набор
        пунктов, и без параметра действие ушло бы в текущее выделение, а не в
        ту подписку, у которой открыли меню.
        """
        group_id = row.group_id
        menu = Gio.Menu()
        menu.append("Обновить", f"win.update-subscription({group_id})")
        menu.append("Редактировать", f"win.edit-subscription({group_id})")
        # Ссылки провайдера есть не у каждой подписки: пустой пункт не показываем.
        if row.web_page_url:
            menu.append("Страница подписки", f"win.open-subscription-page({group_id})")
        if row.support_url:
            menu.append("Поддержка", f"win.open-subscription-support({group_id})")
        menu.append("Удалить", f"win.delete-subscription({group_id})")
        return menu

    def _select(self, group_id: int) -> None:
        self._selected = group_id
        for gid, widget in self._row_widgets.items():
            if gid == group_id:
                widget.add_css_class(SELECTED_CLASS)
            else:
                widget.remove_css_class(SELECTED_CLASS)
        for button, (_label, action, needs_target) in zip(self.buttons, BUTTONS, strict=True):
            if not needs_target:
                continue
            if group_id >= 0:
                button.set_action_target_value(GLib.Variant.new_int32(group_id))
                button.set_action_name(action)
            else:
                button.set_action_name(None)
            button.set_sensitive(group_id >= 0)

    # --- публичное api ---

    def set_data(self, groups: Mapping[int, Any], profile_counts: Mapping[int, int]) -> None:
        """Replace the underlying data and rebuild the list."""
        self._groups = groups
        self._counts = profile_counts
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the list from the current data."""
        self._rebuild()

    def get_selected(self) -> int:
        return self._selected

    # --- аксессоры для тестов ---

    def get_visible_state(self) -> str:
        return "list" if self._rows else "empty"

    def get_empty_text(self) -> str:
        return self._empty_row.get_title()

    def select_for_test(self, *, group_id: int) -> None:
        self._select(group_id)

    def get_row_count(self) -> int:
        return len(self._rows)

    def get_subtitles(self) -> list[str]:
        return [widget.get_subtitle() for widget in self._row_widgets.values()]

    def get_details_for_test(self, *, group_id: int) -> str:
        label = self._details_labels.get(group_id)
        return label.get_text() if label is not None else ""

    def is_expired_for_test(self, *, group_id: int) -> bool:
        label = self._details_labels.get(group_id)
        return label is not None and label.has_css_class("error")

    def is_empty_notice_shown_for_test(self, *, group_id: int) -> bool:
        return group_id in self._empty_labels

    def is_via_fallback_shown_for_test(self, *, group_id: int) -> bool:
        return group_id in self._via_fallback_labels

    def get_announce_for_test(self, *, group_id: int) -> str:
        label = self._announce_labels.get(group_id)
        return label.get_text() if label is not None else ""

    def get_update_button_for_test(self, *, group_id: int) -> Gtk.Button:
        return self._update_buttons[group_id]

    def activate_row_for_test(self, *, group_id: int) -> None:
        self._row_widgets[group_id].emit("activated")

    def is_selected_for_test(self, *, group_id: int) -> bool:
        return self._row_widgets[group_id].has_css_class(SELECTED_CLASS)

    def get_menu_button_for_test(self, *, group_id: int) -> Gtk.MenuButton | None:
        return self._menu_buttons.get(group_id)

    def context_menu_labels_for_test(self, *, group_id: int) -> list[str]:
        menu = self._menu_buttons[group_id].get_menu_model()
        return [
            menu.get_item_attribute_value(index, "label", None).get_string()
            for index in range(menu.get_n_items())
        ]

    def get_menu_target_for_test(self, *, group_id: int) -> int:
        """Return the group id encoded in the row's first menu action."""
        menu = self._menu_buttons[group_id].get_menu_model()
        target = menu.get_item_attribute_value(0, "target", None)
        return target.get_int32()
