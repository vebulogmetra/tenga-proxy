"""Profiles page: a filterable, sortable tree of groups and profiles."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from src.ui.logic.profiles_view import (
    GroupRow,
    ProfileRow,
    SortKey,
    build_profile_rows,
    ping_text,
)

_ACTIVE_CLASS = "profile-active"
_GROUP_CLASS = "profile-group"


class RowItem(GObject.Object):
    """List model wrapper around a group or a profile row.

    `Gtk.TreeListModel` работает только с `GObject`, а dataclass'ы из
    `profiles_view` намеренно остаются обычными объектами Python, чтобы их
    можно было тестировать без GTK.
    """

    __gtype_name__ = "TengaProfileRowItem"

    def __init__(self, row: GroupRow | ProfileRow) -> None:
        super().__init__()
        self.row = row

    @property
    def is_group(self) -> bool:
        return isinstance(self.row, GroupRow)

    @property
    def title(self) -> str:
        return self.row.title

    @property
    def count_text(self) -> str:
        """Profile count of a group, empty for a leaf."""
        return str(self.row.count) if isinstance(self.row, GroupRow) else ""

    @property
    def proxy_type(self) -> str:
        return "" if self.is_group else self.row.proxy_type.upper()

    @property
    def address(self) -> str:
        return "" if self.is_group else self.row.address

    @property
    def ping(self) -> str:
        return "" if self.is_group else ping_text(self.row.latency_ms)

    @property
    def icon_name(self) -> str:
        return self.row.icon_name if isinstance(self.row, GroupRow) else ""


def _new_row_store() -> Gio.ListStore:
    """Create an empty list store holding RowItem instances."""
    return Gio.ListStore.new(RowItem)


class ProfilesPage(Gtk.Box):
    """Search bar, profile tree and the empty state."""

    __gtype_name__ = "TengaProfilesPage"

    __gsignals__ = {
        "profile-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # Второй аргумент — признак группы: набор пунктов меню у группы и у
        # профиля разный, а по одному идентификатору их не различить.
        "profile-context": (GObject.SignalFlags.RUN_FIRST, None, (int, bool)),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._groups: Mapping[int, Any] = {}
        self._profiles: Mapping[int, Iterable[Any]] = {}
        self._query = ""
        self._sort_key = SortKey.NAME
        self._ascending = True
        self._active_profile_id = -1
        self._rows: list[GroupRow] = []

        self._build_search_bar()
        self._build_stack()
        self.refresh()

    # --- построение ---

    def _build_search_bar(self) -> None:
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.set_placeholder_text("Имя, тип, сервер или группа")
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
            icon_name="network-server-symbolic",
            title="Профилей пока нет",
            description="Добавьте профиль по ссылке или подключите подписку.",
        )
        self._stack.add_named(self._empty_page, "empty")

        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        scrolled.set_child(self._build_column_view())
        self._stack.add_named(scrolled, "list")

    def _build_column_view(self) -> Gtk.ColumnView:
        self._tree_model: Gtk.TreeListModel | None = None

        self.column_view = Gtk.ColumnView()
        self.column_view.add_css_class("data-table")
        self.column_view.connect("activate", self._on_row_activated)
        self._install_context_gestures()

        self.column_view.append_column(self._build_name_column())
        self.column_view.append_column(
            self._build_text_column("Тип", lambda item: item.proxy_type, expand=False)
        )
        self.column_view.append_column(
            self._build_text_column("Сервер", lambda item: item.address, expand=True)
        )
        self.column_view.append_column(self._build_ping_column())

        return self.column_view

    def _build_name_column(self) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_name_cell)
        factory.connect("bind", self._bind_name_cell)

        column = Gtk.ColumnViewColumn(title="Имя", factory=factory)
        column.set_expand(True)
        column.set_resizable(True)
        return column

    def _build_text_column(self, title, getter, *, expand: bool) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_label_cell)
        factory.connect("bind", lambda _f, item: self._bind_label_cell(item, getter))

        column = Gtk.ColumnViewColumn(title=title, factory=factory)
        column.set_expand(expand)
        column.set_resizable(True)
        return column

    def _build_ping_column(self) -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_label_cell)
        factory.connect("bind", lambda _f, item: self._bind_label_cell(item, lambda i: i.ping))

        column = Gtk.ColumnViewColumn(title="Пинг", factory=factory)
        column.set_resizable(True)
        return column

    # --- контекстное меню ---

    def _install_context_gestures(self) -> None:
        """Right click and long press both open the row menu."""
        click = Gtk.GestureClick(button=3)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_context_click)
        self.column_view.add_controller(click)

        # Долгое нажатие — тот же жест для сенсорного экрана и трекпада.
        long_press = Gtk.GestureLongPress()
        long_press.set_touch_only(False)
        long_press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        long_press.connect("pressed", self._on_context_long_press)
        self.column_view.add_controller(long_press)

        self._menu_popover = Gtk.PopoverMenu()
        self._menu_popover.set_parent(self.column_view)
        self._menu_popover.set_has_arrow(False)
        self._menu_popover.set_halign(Gtk.Align.START)

    def _on_context_click(self, gesture, _n_press: int, x: float, y: float) -> None:
        position = self._position_at(x, y)
        if position is None:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._open_context_menu(position, x, y)

    def _on_context_long_press(self, _gesture, x: float, y: float) -> None:
        position = self._position_at(x, y)
        if position is not None:
            self._open_context_menu(position, x, y)

    def _position_at(self, x: float, y: float) -> int | None:
        """Find the row index under a pointer position.

        В GTK4 у `Gtk.ColumnView` нет аналога `get_path_at_pos`: строку
        приходится опознавать по виджету под курсором и его порядку среди
        детей списка.
        """
        widget = self.column_view.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self.column_view:
            parent = widget.get_parent()
            if parent is not None and parent.get_css_name() == "listview":
                return self._index_of_child(parent, widget)
            widget = parent
        return None

    @staticmethod
    def _index_of_child(parent: Gtk.Widget, target: Gtk.Widget) -> int | None:
        index = 0
        child = parent.get_first_child()
        while child is not None:
            if child is target:
                return index
            index += 1
            child = child.get_next_sibling()
        return None

    def _open_context_menu(self, position: int, x: float, y: float) -> None:
        """Select the row, report it and pop the menu up over it."""
        item = self._item_at(position)
        if item is None:
            return

        self._select_position(position)
        item_id = item.row.group_id if item.is_group else item.row.profile_id
        self.emit("profile-context", item_id, item.is_group)

        self._menu_popover.set_menu_model(self._menu_model_for(position))
        # Всплывать может только виджет на экране: у неотрисованного списка
        # (страница вне окна, как в тестах) popup() роняет GTK.
        if not self.column_view.get_realized():
            return
        self._menu_popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        self._menu_popover.popup()

    def _menu_model_for(self, position: int) -> Gio.Menu:
        """Build the menu of one row; window actions carry the row id."""
        item = self._item_at(position)
        menu = Gio.Menu()
        if item is None:
            return menu

        if item.is_group:
            group_id = item.row.group_id
            tree_row = self._tree_model.get_row(position)
            expanded = tree_row is not None and tree_row.get_expanded()
            actions = Gio.Menu()
            actions.append(
                "Свернуть группу" if expanded else "Развернуть группу",
                f"win.toggle-group({group_id})",
            )
            actions.append("Тест задержки", "app.test-latency")
            menu.append_section(None, actions)

            edit = Gio.Menu()
            edit.append("Редактировать", f"win.edit-group({group_id})")
            edit.append("Удалить", f"win.delete-group({group_id})")
            menu.append_section(None, edit)
            return menu

        profile_id = item.row.profile_id
        actions = Gio.Menu()
        actions.append("Подключить", f"win.connect-profile({profile_id})")
        actions.append("VPN и маршруты…", f"win.profile-routing({profile_id})")
        actions.append("Тест задержки", f"win.test-profile({profile_id})")
        menu.append_section(None, actions)

        edit = Gio.Menu()
        edit.append("Редактировать", f"win.edit-profile({profile_id})")
        edit.append("Удалить", f"win.delete-profile({profile_id})")
        menu.append_section(None, edit)
        return menu

    def _item_at(self, position: int) -> RowItem | None:
        if self._tree_model is None or position >= self._tree_model.get_n_items():
            return None
        tree_row = self._tree_model.get_row(position)
        return None if tree_row is None else tree_row.get_item()

    def _select_position(self, position: int) -> None:
        selection = self.column_view.get_model()
        if selection is not None:
            selection.set_selected(position)

    # --- фабрики ячеек ---

    def _setup_name_cell(self, _factory, list_item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        icon = Gtk.Image()
        box.append(icon)

        label = Gtk.Label(xalign=0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        box.append(label)

        # Счётчик отдельной меткой: внутри названия он обрезался вместе с ним,
        # а число профилей в группе — то, ради чего строку и разворачивают.
        count = Gtk.Label(xalign=1.0)
        count.add_css_class("dim-label")
        count.add_css_class("caption")
        box.append(count)

        expander = Gtk.TreeExpander()
        expander.set_child(box)
        list_item.set_child(expander)

    def _bind_name_cell(self, _factory, list_item: Gtk.ListItem) -> None:
        tree_row = list_item.get_item()
        item = tree_row.get_item()

        expander = list_item.get_child()
        expander.set_list_row(tree_row)

        box = expander.get_child()
        icon = box.get_first_child()
        label = icon.get_next_sibling()
        count = box.get_last_child()

        icon.set_visible(bool(item.icon_name))
        if item.icon_name:
            icon.set_from_icon_name(item.icon_name)

        label.set_text(item.title)
        count.set_text(item.count_text)
        count.set_visible(bool(item.count_text))

        for css_class in (_ACTIVE_CLASS, _GROUP_CLASS):
            label.remove_css_class(css_class)
        if item.is_group:
            label.add_css_class(_GROUP_CLASS)
        elif item.row.is_active:
            label.add_css_class(_ACTIVE_CLASS)

    def _setup_label_cell(self, _factory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        list_item.set_child(label)

    def _bind_label_cell(self, list_item: Gtk.ListItem, getter) -> None:
        item = list_item.get_item().get_item()
        list_item.get_child().set_text(getter(item))

    # --- модель ---

    def _rebuild_model(self) -> None:
        self._rows = build_profile_rows(
            self._groups,
            self._profiles,
            query=self._query,
            sort_key=self._sort_key,
            ascending=self._ascending,
            active_profile_id=self._active_profile_id,
        )

        root = _new_row_store()
        for group in self._rows:
            root.append(RowItem(group))

        self._tree_model = Gtk.TreeListModel.new(
            root,
            passthrough=False,
            autoexpand=False,
            create_func=self._children_of,
        )
        self.column_view.set_model(Gtk.SingleSelection(model=self._tree_model))
        self._stack.set_visible_child_name("list" if self._rows else "empty")

    def _children_of(self, item: RowItem):
        """Return the child model of a group, or None for a leaf."""
        if not item.is_group or not item.row.children:
            return None

        store = _new_row_store()
        for child in item.row.children:
            store.append(RowItem(child))
        return store

    # --- публичное api ---

    def set_data(
        self,
        groups: Mapping[int, Any],
        profiles_by_group: Mapping[int, Iterable[Any]],
    ) -> None:
        """Replace the underlying data and rebuild the tree."""
        self._groups = groups
        self._profiles = profiles_by_group
        self.refresh()

    def set_query(self, query: str) -> None:
        self._query = query
        self.refresh()

    def set_sort(self, sort_key: SortKey, *, ascending: bool = True) -> None:
        self._sort_key = sort_key
        self._ascending = ascending
        self.refresh()

    def set_active_profile(self, profile_id: int) -> None:
        self._active_profile_id = profile_id
        self.refresh()

    def set_search_enabled(self, enabled: bool) -> None:
        self.search_bar.set_search_mode(enabled)
        if enabled:
            self.search_entry.grab_focus()

    def refresh(self) -> None:
        """Rebuild the tree from the current data, filter and ordering."""
        self._rebuild_model()

    def expand_all(self) -> None:
        """Expand every group.

        Индекс идёт вперёд по живой модели: раскрытие группы вставляет её детей
        сразу за ней, поэтому диапазон, снятый заранее, пропустил бы часть строк.
        """
        if self._tree_model is None:
            return

        index = 0
        while index < self._tree_model.get_n_items():
            row = self._tree_model.get_row(index)
            if row is not None and row.is_expandable():
                row.set_expanded(True)
            index += 1

    def get_selected_profile_id(self) -> int | None:
        """Return the selected profile, or None when a group is selected."""
        selection = self.column_view.get_model()
        if selection is None:
            return None
        tree_row = selection.get_selected_item()
        if tree_row is None:
            return None
        item = tree_row.get_item()
        return None if item.is_group else item.row.profile_id

    # --- обработчики ---

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.set_query(entry.get_text())

    def _on_row_activated(self, _view: Gtk.ColumnView, position: int) -> None:
        self._activate_position(position)

    def _activate_position(self, position: int) -> None:
        if self._tree_model is None:
            return
        tree_row = self._tree_model.get_row(position)
        if tree_row is None:
            return

        item = tree_row.get_item()
        if item.is_group:
            tree_row.set_expanded(not tree_row.get_expanded())
            return

        self.emit("profile-activated", item.row.profile_id)

    # --- аксессоры для тестов ---

    def get_visible_state(self) -> str:
        return self._stack.get_visible_child_name()

    def get_root_count(self) -> int:
        return len(self._rows)

    def get_visible_row_count(self) -> int:
        return 0 if self._tree_model is None else self._tree_model.get_n_items()

    def get_profile_titles(self, *, group_id: int) -> list[str]:
        for group in self._rows:
            if group.group_id == group_id:
                return [child.title for child in group.children]
        return []

    def get_active_titles(self) -> list[str]:
        return [child.title for group in self._rows for child in group.children if child.is_active]

    def activate_row_for_test(self, position: int) -> None:
        self._activate_position(position)

    def get_selected_position(self) -> int:
        selection = self.column_view.get_model()
        return -1 if selection is None else selection.get_selected()

    def emit_context_for_test(self, *, position: int) -> None:
        self._open_context_menu(position, 0.0, 0.0)

    def context_menu_labels_for_test(self, *, position: int) -> list[str]:
        menu = self._menu_model_for(position)
        return _menu_labels(menu)

    def emit_activation_for_test(self, *, profile_id: int) -> None:
        for position in range(self.get_visible_row_count()):
            tree_row = self._tree_model.get_row(position)
            item = tree_row.get_item()
            if not item.is_group and item.row.profile_id == profile_id:
                self._activate_position(position)
                return


def _menu_labels(menu: Gio.MenuModel) -> list[str]:
    """Flatten a menu model into its labels, sections included."""
    labels: list[str] = []
    for index in range(menu.get_n_items()):
        label = menu.get_item_attribute_value(index, "label", None)
        if label is not None:
            labels.append(label.get_string())
        for link in ("section", "submenu"):
            child = menu.get_item_link(index, link)
            if child is not None:
                labels.extend(_menu_labels(child))
    return labels
