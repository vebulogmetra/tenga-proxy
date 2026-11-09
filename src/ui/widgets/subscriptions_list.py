"""Subscription list of the settings section «Подписки»: a table, menus and buttons."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from src.ui.logic.subscriptions_view import (
    EMPTY_RESPONSE_HINT,
    EMPTY_RESPONSE_TEXT,
    VIA_FALLBACK_TEXT,
    SubscriptionRow,
    build_subscription_rows,
)

EMPTY_TEXT = "Подписок нет. Добавьте ссылку от провайдера."
SELECTED_CLASS = "subscription-selected"
ALT_CLASS = "subscription-alt"
# Колонки — как у таблицы Qt; название и трафик растягиваются.
COLUMNS = ("Название", "Серверов", "Обновлено", "Трафик и срок")
BUTTONS = (
    ("Добавить…", "app.add-subscription", False),
    ("Обновить", "win.update-subscription", True),
    ("Изменить…", "win.edit-subscription", True),
    ("Удалить", "win.delete-subscription", True),
)


class SubscriptionsList(Adw.PreferencesGroup):
    """Subscription table with row menus; buttons below act on the selected row."""

    __gtype_name__ = "TengaSubscriptionsList"

    def __init__(self) -> None:
        super().__init__(title="Подписки")

        self._groups: Mapping[int, Any] = {}
        self._counts: Mapping[int, int] = {}
        self._rows: list[SubscriptionRow] = []
        self._selected = -1
        self._row_widgets: dict[int, Gtk.ListBoxRow] = {}
        self._url_labels: dict[int, Gtk.Label] = {}
        # Ячейки строк в группах размеров: группа держит ширину по всем своим
        # виджетам, поэтому ячейки удалённых строк из неё убираются.
        self._sized: list[tuple[Gtk.SizeGroup, Gtk.Widget]] = []
        self._update_buttons: dict[int, Gtk.Button] = {}
        self._menu_buttons: dict[int, Gtk.MenuButton] = {}
        self._details_labels: dict[int, Gtk.Label] = {}
        self._announce_labels: dict[int, Gtk.Label] = {}
        self._empty_labels: dict[int, Gtk.Label] = {}
        self._via_fallback_labels: dict[int, Gtk.Label] = {}

        # Колонки строк выравниваются по заголовку через группы размеров:
        # растягиваемые тоже, иначе запас делится от разной естественной ширины.
        self._name_size = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._details_size = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._count_size = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._updated_size = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self._actions_size = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        # Свой список, а не строки группы: заголовок колонок и чередование
        # фона нужны внутри одной рамки.
        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._list.add_css_class("subscriptions-table")
        self._list.connect("row-activated", self._on_row_activated)
        self.add(self._list)

        self._header = self._build_header()
        self._list.append(self._header)
        # Ячейки заголовка остаются в группах навсегда.
        self._sized.clear()

        self._empty_row = Adw.ActionRow(title=EMPTY_TEXT, activatable=False)
        self._empty_row.add_css_class("dim-label")
        self._list.append(self._empty_row)

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

    def _cells(
        self,
        name: Gtk.Widget,
        count: Gtk.Widget,
        updated: Gtk.Widget,
        details: Gtk.Widget,
        actions: Gtk.Widget,
    ) -> Gtk.Box:
        """One table line: name and details stretch, the rest fit their content."""
        box = Gtk.Box(spacing=8)
        box.add_css_class("subscription-cells")
        name.set_hexpand(True)
        details.set_hexpand(True)
        for group, cell in (
            (self._name_size, name),
            (self._count_size, count),
            (self._updated_size, updated),
            (self._details_size, details),
            (self._actions_size, actions),
        ):
            group.add_widget(cell)
            self._sized.append((group, cell))
        for cell in (name, count, updated, details, actions):
            box.append(cell)
        return box

    def _build_header(self) -> Gtk.ListBoxRow:
        labels = []
        for index, title in enumerate(COLUMNS):
            label = Gtk.Label(label=title, xalign=0.5 if index == 1 else 0.0)
            label.add_css_class("caption-heading")
            label.add_css_class("dim-label")
            labels.append(label)
        labels[1].set_size_request(72, -1)
        labels[2].set_size_request(90, -1)
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.add_css_class("subscription-header")
        row.set_child(self._cells(*labels, Gtk.Box()))
        return row

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        for gid, widget in self._row_widgets.items():
            if widget is row:
                self._select(gid)
                return

    def _rebuild(self) -> None:
        for group, cell in self._sized:
            group.remove_widget(cell)
        self._sized.clear()
        for widget in self._row_widgets.values():
            self._list.remove(widget)
        self._row_widgets.clear()
        self._url_labels.clear()
        self._update_buttons.clear()
        self._menu_buttons.clear()
        self._details_labels.clear()
        self._announce_labels.clear()
        self._empty_labels.clear()
        self._via_fallback_labels.clear()

        self._rows = build_subscription_rows(self._groups, self._counts)

        for index, row in enumerate(self._rows):
            widget = self._build_row(row)
            # Чередование фона, как в таблице Qt: длинную строку легче
            # проследить до её кнопок.
            if index % 2:
                widget.add_css_class(ALT_CLASS)
            self._list.append(widget)
        self._header.set_visible(bool(self._rows))
        self._empty_row.set_visible(not self._rows)

        ids = [row.group_id for row in self._rows]
        self._select(self._selected if self._selected in ids else (ids[0] if ids else -1))

    def _build_row(self, row: SubscriptionRow) -> Gtk.ListBoxRow:
        # Имя и адрес приходят извне: обычный текст, амперсанд — не разметка.
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=row.name, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("subscription-name")
        title.set_tooltip_text(row.name)
        name_box.append(title)
        url = Gtk.Label(label=row.url, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        url.add_css_class("caption")
        url.add_css_class("dim-label")
        url.set_tooltip_text(row.url)
        name_box.append(url)
        self._url_labels[row.group_id] = url

        count = Gtk.Label(label=str(row.profile_count), xalign=0.5)
        count.add_css_class("numeric")
        count.set_size_request(72, -1)
        updated = Gtk.Label(label=row.updated_text, xalign=0.0)
        updated.set_tooltip_text(row.updated_text)
        updated.set_size_request(90, -1)

        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        if row.details_text:
            details = self._cell_label(row.details_text)
            # Истёкшую подписку видно сразу: серверов в ней обычно уже нет.
            details.add_css_class("error" if row.expired else "dim-label")
            details_box.append(details)
            self._details_labels[row.group_id] = details
        if row.empty:
            # Без пометки сохранённые серверы выглядели бы рабочими.
            empty = self._cell_label(EMPTY_RESPONSE_TEXT)
            empty.add_css_class("error")
            empty.set_tooltip_text(EMPTY_RESPONSE_HINT)
            details_box.append(empty)
            self._empty_labels[row.group_id] = empty
        if row.via_fallback:
            via_fallback = self._cell_label(VIA_FALLBACK_TEXT)
            via_fallback.add_css_class("dim-label")
            details_box.append(via_fallback)
            self._via_fallback_labels[row.group_id] = via_fallback

        actions = Gtk.Box(spacing=2, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        if row.announce:
            actions.append(self._build_announce_button(row))

        button = Gtk.Button(icon_name="view-refresh-symbolic")
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text("Обновить подписку")
        button.add_css_class("flat")
        # Действие окна, как у пунктов меню: диалог настроек живёт внутри окна.
        button.set_action_name("win.update-subscription")
        button.set_action_target_value(GLib.Variant.new_int32(row.group_id))
        actions.append(button)

        menu_button = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_button.set_valign(Gtk.Align.CENTER)
        menu_button.set_tooltip_text("Действия")
        menu_button.add_css_class("flat")
        menu_button.set_menu_model(self._menu_model_for(row))
        actions.append(menu_button)

        list_row = Gtk.ListBoxRow(activatable=True)
        list_row.add_css_class("subscription-row")
        # Ширину колонки задаёт группа размеров; кнопки прижаты к её правому
        # краю, чтобы «Обновить» и меню стояли друг под другом и без объявления.
        actions_cell = Gtk.Box()
        actions.set_hexpand(True)
        actions_cell.append(actions)
        list_row.set_child(self._cells(name_box, count, updated, details_box, actions_cell))
        list_row.update_property([Gtk.AccessibleProperty.LABEL], [row.name])

        self._row_widgets[row.group_id] = list_row
        self._update_buttons[row.group_id] = button
        self._menu_buttons[row.group_id] = menu_button
        return list_row

    @staticmethod
    def _cell_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        label.set_tooltip_text(text)
        return label

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

    def is_header_shown_for_test(self) -> bool:
        return self._header.get_visible()

    def is_alternate_for_test(self, *, group_id: int) -> bool:
        return self._row_widgets[group_id].has_css_class(ALT_CLASS)

    def select_for_test(self, *, group_id: int) -> None:
        self._select(group_id)

    def get_row_count(self) -> int:
        return len(self._rows)

    def get_subtitles(self) -> list[str]:
        return [label.get_text() for label in self._url_labels.values()]

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
        self._list.emit("row-activated", self._row_widgets[group_id])

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
