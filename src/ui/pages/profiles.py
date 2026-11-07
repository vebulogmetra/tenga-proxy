"""Servers page: search and tools, a two-line tree of groups and servers, the selection row."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from src.ui.logic.latency import PingProgress
from src.ui.logic.menus import ADD_MENU
from src.ui.logic.profiles_view import (
    EMPTY_DESCRIPTION,
    EMPTY_TITLE,
    NO_RESULTS_TEXT,
    SEARCH_PLACEHOLDER,
    GroupRow,
    ProfileRow,
    SortKey,
    build_profile_rows,
    group_count_text,
    group_details,
    ping_text,
    selected_text,
)
from src.ui.logic.status import SWITCH_LABEL, switch_hint
from src.ui.logic.subscriptions_view import build_subscription_rows
from src.ui.widgets.profile_row import GroupRowWidget, ProfileRowWidget

_LIST_CLASS = "profiles-list"

SORT_MENU = (
    (SortKey.NAME, "По имени"),
    (SortKey.TYPE, "По типу"),
    (SortKey.PING, "По задержке"),
)


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
    def proxy_type(self) -> str:
        return "" if self.is_group else self.row.proxy_type.upper()

    @property
    def address(self) -> str:
        return "" if self.is_group else self.row.address


# Сколько проходов разметки удерживать прокрутку после пересборки.
_SCROLL_RESTORE_ATTEMPTS = 40


def _new_row_store() -> Gio.ListStore:
    """Create an empty list store holding RowItem instances."""
    return Gio.ListStore.new(RowItem)


class ProfilesPage(Gtk.Box):
    """Tools row, server tree with its empty state, and the selection row."""

    __gtype_name__ = "TengaProfilesPage"

    __gsignals__ = {
        "profile-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # Второй аргумент — признак группы: набор пунктов меню у группы и у
        # профиля разный, а по одному идентификатору их не различить.
        "profile-context": (GObject.SignalFlags.RUN_FIRST, None, (int, bool)),
        # Выделение задаёт цель «Подключить» и строку «Выбран: …».
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Кнопка «Пинг» в строке: проверить только этот сервер.
        "profile-ping": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # «Переключить на выбранный» под списком.
        "switch-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.add_css_class("library-card")
        self.set_vexpand(True)

        self._groups: Mapping[int, Any] = {}
        self._profiles: Mapping[int, Iterable[Any]] = {}
        self._query = ""
        self._rebuilding = False
        self._sort_key = SortKey.NAME
        self._ascending = True
        self._active_profile_id = -1
        self._rows: list[GroupRow] = []
        self._details: dict[int, tuple[str, bool]] = {}
        self._ping_progress: PingProgress | None = None
        # Строки, которые сейчас на экране: прогресс пинга двигается в них
        # напрямую, без пересборки модели на каждый результат.
        self._group_cells: dict[int, GroupRowWidget] = {}
        self._profile_cells: dict[int, ProfileRowWidget] = {}

        self._build_actions()
        self._build_tools()
        self._build_stack()
        self._build_selection_row()
        self.refresh()

    # --- построение ---

    def _build_actions(self) -> None:
        # Действия страницы, а не окна: сортировка — свойство списка, и тесты
        # страницы не должны зависеть от окна.
        group = Gio.SimpleActionGroup()
        sort = Gio.SimpleAction.new("sort", GLib.VariantType.new("s"))
        sort.connect("activate", lambda _a, value: self._choose_sort(SortKey(value.get_string())))
        group.add_action(sort)
        self.insert_action_group("page", group)

    def _build_tools(self) -> None:
        tools = Gtk.Box(spacing=8)

        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.set_placeholder_text(SEARCH_PLACEHOLDER)
        self.search_entry.connect("search-changed", self._on_search_changed)
        tools.append(self.search_entry)

        add_menu = Gio.Menu()
        for name, label in ADD_MENU:
            add_menu.append(label, f"app.{name}")
        self.add_button = Gtk.MenuButton(label="Добавить…", menu_model=add_menu)
        tools.append(self.add_button)

        sort_menu = Gio.Menu()
        for key, label in SORT_MENU:
            sort_menu.append(label, f"page.sort('{key.value}')")
        self.sort_button = Gtk.MenuButton(label="Сортировка", menu_model=sort_menu)
        tools.append(self.sort_button)

        self.append(tools)

    def _build_stack(self) -> None:
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_vexpand(True)
        self.append(self._stack)

        self._empty_page = Adw.StatusPage(
            icon_name="network-server-symbolic",
            title=EMPTY_TITLE,
            description=EMPTY_DESCRIPTION,
        )
        self._stack.add_named(self._empty_page, "empty")

        self._scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
        )
        self._scrolled.set_child(self._build_list_view())
        self._stack.add_named(self._scrolled, "list")

    def _build_list_view(self) -> Gtk.ListView:
        self._tree_model: Gtk.TreeListModel | None = None
        self._root_store: Gio.ListStore | None = None

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        factory.connect("unbind", self._unbind_row)

        self.list_view = Gtk.ListView(factory=factory)
        self.list_view.add_css_class(_LIST_CLASS)
        self.list_view.connect("activate", self._on_row_activated)
        self._install_context_gestures()
        return self.list_view

    def _build_selection_row(self) -> None:
        row = Gtk.Box(spacing=8)
        row.add_css_class("selection-row")
        self._selection_label = Gtk.Label(
            xalign=0.0, hexpand=True, ellipsize=Pango.EllipsizeMode.END
        )
        self._selection_label.add_css_class("dim-label")
        row.append(self._selection_label)

        # Выделение другой строки соединение не меняет: переход на неё —
        # отдельное явное действие, видимое только пока выбран не активный.
        self.switch_button = Gtk.Button(label=SWITCH_LABEL, visible=False, halign=Gtk.Align.END)
        self.switch_button.connect("clicked", lambda _button: self.emit("switch-clicked"))
        row.append(self.switch_button)
        self.append(row)
        self.connect("selection-changed", lambda _page: self._update_selection_row())

    # --- контекстное меню ---

    def _install_context_gestures(self) -> None:
        """Right click and long press both open the row menu."""
        click = Gtk.GestureClick(button=3)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_context_click)
        self.list_view.add_controller(click)

        # Долгое нажатие — тот же жест для сенсорного экрана и трекпада.
        long_press = Gtk.GestureLongPress()
        long_press.set_touch_only(False)
        long_press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        long_press.connect("pressed", self._on_context_long_press)
        self.list_view.add_controller(long_press)

        self._menu_popover = Gtk.PopoverMenu()
        self._menu_popover.set_parent(self.list_view)
        self._menu_popover.set_has_arrow(False)
        # Выравнивание не задаётся: popover позиционируется по set_pointing_to,
        # то есть по точке клика, а halign прижал бы его к краю списка.

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

        В GTK4 у `Gtk.ListView` нет аналога `get_path_at_pos`: строку
        приходится опознавать по виджету под курсором и его порядку среди
        детей списка.
        """
        widget = self.list_view.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self.list_view:
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
        if not self.list_view.get_realized():
            return
        # Поля задаются присваиванием: Gdk.Rectangle — boxed-тип, аргументы
        # конструктора он молча игнорирует, и меню прилипало к углу списка.
        point = Gdk.Rectangle()
        point.x = int(x)
        point.y = int(y)
        point.width = 1
        point.height = 1
        self._menu_popover.set_pointing_to(point)
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
            if item.row.is_subscription:
                actions.append("Обновить подписку", f"win.update-subscription({group_id})")
            actions.append("Тест задержки", f"win.test-group({group_id})")
            actions.append("Оставить рабочие…", f"win.keep-working({group_id})")
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
        selection = self.list_view.get_model()
        if selection is not None:
            selection.set_selected(position)

    # --- фабрика строк ---

    def _setup_row(self, _factory, list_item: Gtk.ListItem) -> None:
        profile = ProfileRowWidget()
        profile.connect("ping-clicked", self._on_row_ping)
        profile.connect("menu-clicked", self._on_row_menu)
        group = GroupRowWidget()
        box = Gtk.Box()
        box.append(group)
        box.append(profile)
        for widget in (group, profile):
            widget.set_hexpand(True)
        expander = Gtk.TreeExpander(child=box)
        list_item.set_child(expander)

    def _bind_row(self, _factory, list_item: Gtk.ListItem) -> None:
        tree_row = list_item.get_item()
        item = tree_row.get_item()

        expander = list_item.get_child()
        expander.set_list_row(tree_row)
        box = expander.get_child()
        group, profile = box.get_first_child(), box.get_last_child()
        group.set_visible(item.is_group)
        profile.set_visible(not item.is_group)

        if item.is_group:
            self._group_cells[item.row.group_id] = group
            self._show_group(group, item.row)
        else:
            self._profile_cells[item.row.profile_id] = profile
            profile.bind(item.row)

    def _unbind_row(self, _factory, list_item: Gtk.ListItem) -> None:
        box = list_item.get_child().get_child()
        group, profile = box.get_first_child(), box.get_last_child()
        for cells, widget in ((self._group_cells, group), (self._profile_cells, profile)):
            for key, cell in list(cells.items()):
                if cell is widget:
                    del cells[key]

    def _show_group(self, widget: GroupRowWidget, row: GroupRow) -> None:
        """Fill a group row: summary, subscription details and the latency progress."""
        details, expired = self._details.get(row.group_id, ("", False))
        progress = self._ping_progress
        fraction = progress.fraction(row.group_id) if progress is not None else None
        widget.bind(
            group_id=row.group_id,
            title=row.title,
            icon_name=row.icon_name,
            summary=group_details(row, progress, details),
            fraction=fraction,
            expired=expired,
        )

    def _on_row_ping(self, widget: ProfileRowWidget) -> None:
        if widget.row is not None:
            self.emit("profile-ping", widget.row.profile_id)

    def _on_row_menu(self, widget: ProfileRowWidget) -> None:
        if widget.row is None:
            return
        position = self._position_of_profile(widget.row.profile_id)
        if position is None:
            return
        self._select_position(position)
        self.emit("profile-context", widget.row.profile_id, False)
        menu = Gtk.PopoverMenu(menu_model=self._menu_model_for(position), has_arrow=True)
        menu.set_parent(widget.menu_button)
        menu.connect("closed", lambda popover: GLib.idle_add(popover.unparent))
        if widget.menu_button.get_realized():
            menu.popup()

    def _position_of_profile(self, profile_id: int) -> int | None:
        if self._tree_model is None:
            return None
        for position in range(self._tree_model.get_n_items()):
            item = self._item_at(position)
            if item is not None and not item.is_group and item.row.profile_id == profile_id:
                return position
        return None

    def _position_of_group(self, group_id: int) -> int | None:
        if self._tree_model is None:
            return None
        for position in range(self._tree_model.get_n_items()):
            item = self._item_at(position)
            if item is not None and item.is_group and item.row.group_id == group_id:
                return position
        return None

    # --- модель ---

    def _rebuild_model(self) -> None:
        # Раскрытие живёт в Gtk.TreeListRow, а корневой store переписывается:
        # без переноса состояния группы схлопывались бы на каждом обновлении —
        # например на каждой порции результатов пинга.
        expanded = self._expanded_group_ids()
        # Выделение тоже теряется: splice убирает выбранную строку, и
        # SingleSelection перескакивает на группу. «Подключить» берёт профиль
        # из выделения, поэтому без переноса оно после отключения пустело.
        selected_id = self.get_selected_profile_id()
        # splice и перенос выделения дёргают его по нескольку раз: наружу
        # уходит одно уведомление после перестройки.
        self._rebuilding = True

        self._rows = build_profile_rows(
            self._groups,
            self._profiles,
            query=self._query,
            sort_key=self._sort_key,
            ascending=self._ascending,
            active_profile_id=self._active_profile_id,
        )

        self._details = {
            row.group_id: (row.details_text, row.expired)
            for row in build_subscription_rows(self._groups, {})
        }
        items = [RowItem(group) for group in self._rows]

        # Модель меняется на месте, а не заводится заново: новая модель в
        # ListView сбрасывает прокрутку в ноль, а счётчик трафика зовёт
        # обновление раз в секунду — список было невозможно листать.
        if self._tree_model is None:
            self._root_store = _new_row_store()
            self._root_store.splice(0, 0, items)
            self._tree_model = Gtk.TreeListModel.new(
                self._root_store,
                passthrough=False,
                autoexpand=False,
                create_func=self._children_of,
            )
            selection = Gtk.SingleSelection(model=self._tree_model)
            selection.connect("selection-changed", self._on_selection_changed)
            self.list_view.set_model(selection)
        else:
            self._root_store.splice(0, self._root_store.get_n_items(), items)

        self._restore_expanded(expanded)
        if selected_id is not None:
            self.select_profile(selected_id)
        self._rebuilding = False
        if self.get_selected_profile_id() != selected_id:
            self.emit("selection-changed")
        self._stack.set_visible_child_name("list" if self._rows else "empty")
        self._update_empty_page()
        self._update_selection_row()

    def _update_empty_page(self) -> None:
        if self._query.strip():
            self._empty_page.set_icon_name("edit-find-symbolic")
            self._empty_page.set_title(NO_RESULTS_TEXT)
            self._empty_page.set_description(None)
        else:
            self._empty_page.set_icon_name("network-server-symbolic")
            self._empty_page.set_title(EMPTY_TITLE)
            self._empty_page.set_description(EMPTY_DESCRIPTION)

    def _selected_item(self) -> RowItem | None:
        selection = self.list_view.get_model()
        tree_row = None if selection is None else selection.get_selected_item()
        return None if tree_row is None else tree_row.get_item()

    def _update_selection_row(self) -> None:
        item = self._selected_item()
        if item is None or item.is_group:
            self._selection_label.set_text(selected_text(""))
            self._selection_label.set_tooltip_text(None)
            return
        self._selection_label.set_text(selected_text(item.title))
        details = " · ".join(part for part in (item.proxy_type, item.address) if part)
        self._selection_label.set_tooltip_text(details or None)

    def _on_selection_changed(self, *_args) -> None:
        if not self._rebuilding:
            self.emit("selection-changed")

    def _preserve_scroll(self, rebuild: Callable[[], None]) -> None:
        """Run a model rebuild without moving the visible part of the list.

        Строки пересоздаются целиком, поэтому ListView успевает укоротить
        содержимое и подтянуть прокрутку к нулю. Значение снимается до
        перестройки и возвращается, когда высота уже пересчитана.
        """
        adjustment = self._scrolled.get_vadjustment()
        offset = adjustment.get_value()

        rebuild()

        if offset <= 0:
            return

        # Возврат повторяется несколько проходов разметки подряд. Пересборка
        # схлопывает группы: adjustment обрезается до высоты одного экрана,
        # раскрытие возвращает высоту, и ListView доводит прокрутку до
        # видимой строки уже после первого восстановления. Одного прохода не
        # хватает — значение перетиралось на строку вниз каждый тик.
        attempts = 0

        def _restore() -> bool:
            nonlocal attempts
            attempts += 1
            if adjustment.get_value() != offset:
                adjustment.set_value(offset)
            if attempts >= _SCROLL_RESTORE_ATTEMPTS:
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        adjustment.set_value(offset)
        GLib.idle_add(_restore)

    def _expanded_group_ids(self) -> set[int]:
        """Collect the groups currently expanded in the tree."""
        if self._tree_model is None:
            return set()

        ids: set[int] = set()
        for position in range(self._tree_model.get_n_items()):
            tree_row = self._tree_model.get_row(position)
            if tree_row is None or not tree_row.get_expanded():
                continue
            item = tree_row.get_item()
            if item.is_group:
                ids.add(item.row.group_id)
        return ids

    def _restore_expanded(self, group_ids: set[int]) -> None:
        """Re-expand the groups that were open before the rebuild."""
        if self._tree_model is None or not group_ids:
            return

        # Индекс идёт вперёд по живой модели: раскрытие вставляет детей сразу
        # за группой, поэтому заранее снятый диапазон пропустил бы строки.
        position = 0
        while position < self._tree_model.get_n_items():
            tree_row = self._tree_model.get_row(position)
            if tree_row is not None:
                item = tree_row.get_item()
                if item.is_group and item.row.group_id in group_ids:
                    tree_row.set_expanded(True)
            position += 1

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
        # Без проверки страница перестраивалась дважды за один refresh_pages:
        # активный профиль между тиками счётчика трафика не меняется, а лишняя
        # пересборка сдвигала прокрутку на строку вниз.
        if profile_id == self._active_profile_id:
            return
        self._active_profile_id = profile_id
        self.refresh()

    def _choose_sort(self, sort_key: SortKey) -> None:
        """Pick a sort key; picking the current one again flips the direction."""
        if sort_key == self._sort_key:
            self.set_sort(sort_key, ascending=not self._ascending)
        else:
            self.set_sort(sort_key, ascending=True)

    def set_ping_progress(self, progress: PingProgress | None) -> None:
        """Show the progress of a latency run in the group rows; None hides it."""
        self._ping_progress = progress
        for group_id in list(self._group_cells):
            self.update_group_progress(group_id)

    def update_group_progress(self, group_id: int) -> None:
        """Redraw the progress of one group after a result arrived."""
        widget = self._group_cells.get(group_id)
        if widget is None:
            return
        for row in self._rows:
            if row.group_id == group_id:
                self._show_group(widget, row)
                return

    def focus_search(self) -> None:
        """Move the keyboard focus into the search field, selecting its text."""
        self.search_entry.grab_focus()
        self.search_entry.select_region(0, -1)

    def set_switch_target(self, name: str, *, enabled: bool) -> None:
        """Offer to switch to the named server; an empty name hides the button."""
        self.switch_button.set_visible(bool(name))
        self.switch_button.set_tooltip_text(switch_hint(name) if name else None)
        self.switch_button.set_sensitive(enabled)

    def refresh(self) -> None:
        """Rebuild the tree from the current data, filter and ordering."""
        self._preserve_scroll(self._rebuild_model)

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

    def toggle_group(self, group_id: int) -> None:
        """Expand or collapse one group by its identifier."""
        if self._tree_model is None:
            return

        for position in range(self._tree_model.get_n_items()):
            tree_row = self._tree_model.get_row(position)
            if tree_row is None:
                continue
            item = tree_row.get_item()
            if item.is_group and item.row.group_id == group_id:
                tree_row.set_expanded(not tree_row.get_expanded())
                return

    def select_profile(self, profile_id: int) -> bool:
        """Select a visible profile row; False when it is not shown."""
        if self._tree_model is None:
            return False
        for position in range(self._tree_model.get_n_items()):
            item = self._item_at(position)
            if item is not None and not item.is_group and item.row.profile_id == profile_id:
                self._select_position(position)
                return True
        return False

    def get_selected_profile_id(self) -> int | None:
        """Return the selected profile, or None when a group is selected."""
        item = self._selected_item()
        return None if item is None or item.is_group else item.row.profile_id

    # --- обработчики ---

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.set_query(entry.get_text())

    def _on_row_activated(self, _view: Gtk.ListView, position: int) -> None:
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

    def group_progress_for_test(self, group_id: int) -> tuple[str, float] | None:
        """Count text and fraction of a visible group's bar, None when hidden."""
        widget = self._group_cells.get(group_id)
        if widget is None or not widget.progress.get_visible():
            return None
        row = next(row for row in self._rows if row.group_id == group_id)
        return group_count_text(row, self._ping_progress), widget.progress.get_fraction()

    def row_widget_for_test(self, *, profile_id: int | None = None, group_id: int | None = None):
        if profile_id is not None:
            return self._profile_cells.get(profile_id)
        return self._group_cells.get(group_id)

    def menu_labels_for_test(self, button: Gtk.MenuButton) -> list[str]:
        return _menu_labels(button.get_menu_model())

    def activate_sort_for_test(self, key: str) -> None:
        self.activate_action("page.sort", GLib.Variant.new_string(key))

    def get_sort_for_test(self) -> tuple[SortKey, bool]:
        return self._sort_key, self._ascending

    def get_empty_title(self) -> str:
        return self._empty_page.get_title()

    def get_selection_text(self) -> str:
        return self._selection_label.get_text()

    def get_vadjustment_for_test(self) -> Gtk.Adjustment:
        return self._scrolled.get_vadjustment()

    def get_sort_key_for_test(self) -> SortKey:
        return self._sort_key

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
        selection = self.list_view.get_model()
        return -1 if selection is None else selection.get_selected()

    def emit_context_for_test(self, *, position: int) -> None:
        self._open_context_menu(position, 0.0, 0.0)

    def context_menu_labels_for_test(
        self,
        *,
        position: int | None = None,
        profile_id: int | None = None,
        group_id: int | None = None,
    ) -> list[str]:
        if profile_id is not None:
            position = self._position_of_profile(profile_id)
        elif group_id is not None:
            position = self._position_of_group(group_id)
        if position is None:
            return []
        return _menu_labels(self._menu_model_for(position))

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
