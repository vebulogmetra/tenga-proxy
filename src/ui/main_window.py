from __future__ import annotations

import array
import threading
import time
import datetime
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from src.db.config import RoutingMode
from src.sys.vpn import is_vpn_active
from src.ui.dialogs import (
    show_edit_group_dialog,
    show_edit_profile_dialog,
    show_profile_vpn_settings_dialog,
    show_subscription_dialog,
)
from src.ui.style import style_widget_tree, style_window
from src.sub.updater import SubscriptionUpdater

if TYPE_CHECKING:
    from src.core.context import AppContext, ProxyState


def format_bytes(bytes_count: int) -> str:
    """Format bytes to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    if bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    if bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


class MainWindow(Gtk.Window):
    """Main application window."""

    def __init__(self, context: AppContext):
        super().__init__(title="Tenga Proxy")

        self._context = context

        # Callbacks
        self._on_connect: Callable[[int], None] | None = None
        self._on_disconnect: Callable[[], None] | None = None
        self._on_config_reload: Callable[[], None] | None = None
        self._on_test_latency: Callable[[int], int] | None = None
        # UI elements
        self._profile_list: Gtk.TreeView | None = None
        self._profile_store: Gtk.TreeStore | None = None
        self._profile_filter_entry: Gtk.SearchEntry | None = None
        self._profiles_stack: Gtk.Stack | None = None
        self._profiles_empty_label: Gtk.Label | None = None
        self._subscription_list: Gtk.TreeView | None = None
        self._subscription_store: Gtk.ListStore | None = None
        self._subscription_filter_entry: Gtk.SearchEntry | None = None
        self._subscriptions_stack: Gtk.Stack | None = None
        self._subscriptions_empty_label: Gtk.Label | None = None
        self._connect_button: Gtk.Button | None = None
        self._status_label: Gtk.Label | None = None
        self._header_icon: Gtk.Image | None = None
        self._header_button: Gtk.Button | None = None
        self._logo_color: GdkPixbuf.Pixbuf | None = None
        self._logo_gray: GdkPixbuf.Pixbuf | None = None
        self._connecting: bool = False
        # Delay label
        self._delay_label: Gtk.Label | None = None
        self._routing_mode_label: Gtk.Label | None = None
        self._routing_direct_status: Gtk.Label | None = None
        self._routing_proxy_status: Gtk.Label | None = None
        self._routing_vpn_status: Gtk.Label | None = None
        # Monitoring UI elements
        self._monitoring_proxy_status: Gtk.Label | None = None
        self._monitoring_vpn_status: Gtk.Label | None = None
        self._monitoring_last_check: Gtk.Label | None = None
        self._monitoring_notebook: Gtk.Notebook | None = None
        self._monitoring_page: Gtk.Widget | None = None
        self._monitoring_page_index: int = -1
        # Window state tracking
        self._saved_width: int = 400
        self._saved_height: int = 390
        self._saved_x: int | None = None
        self._saved_y: int | None = None
        self._is_maximized: bool = False
        # Profile sort state
        self._profile_sort_key: str | None = None  # "type" | "ping" | None
        self._profile_sort_ascending: bool = True
        self._col_type: Gtk.TreeViewColumn | None = None
        self._col_ping: Gtk.TreeViewColumn | None = None

        self._setup_window()
        self._setup_ui()

        # Subscribe to state changes
        self._context.proxy_state.add_listener(self._on_state_changed)
        # Initial update
        self._refresh_profiles()
        self._refresh_subscriptions()
        self._update_ui(self._context.proxy_state)
        self._update_monitoring_tab_visibility()

    def _setup_window(self) -> None:
        """Setup window."""
        self._load_window_geometry()
        self.set_default_size(self._saved_width, self._saved_height)
        self.set_size_request(350, 340)
        self.set_resizable(True)
        if self._saved_x is None or self._saved_y is None:
            self.set_position(Gtk.WindowPosition.CENTER)
        else:
            self.set_position(Gtk.WindowPosition.NONE)
        self.set_border_width(10)
        from src.core.config import get_asset_path

        app_icon_path = get_asset_path("tenga-proxy.png")
        if app_icon_path.exists():
            try:
                self.set_icon_from_file(str(app_icon_path))
            except Exception:
                self.set_icon_name("network-transmit-receive")
        else:
            self.set_icon_name("network-transmit-receive")

        self.set_wmclass("tenga-proxy", "tenga-proxy")
        self.set_role("tenga-proxy")
        self.connect("realize", self._on_realize)

        # On close - hide
        self.connect("delete-event", self._on_delete)
        self.connect("destroy", self._on_destroy)
        self.connect("window-state-event", self._on_window_state_event)
        self.connect("configure-event", self._on_configure_event)
        style_window(self)

    def _setup_ui(self) -> None:
        """Setup UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.get_style_context().add_class("tenga-root")
        self.add(main_box)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_halign(Gtk.Align.CENTER)
        self._load_logo_pixbufs()
        self._header_icon = Gtk.Image()
        if self._logo_gray is not None:
            self._header_icon.set_from_pixbuf(self._logo_gray)
        else:
            self._header_icon.set_from_icon_name("tenga-proxy", Gtk.IconSize.DIALOG)
            self._header_icon.set_pixel_size(64)
        self._header_button = Gtk.Button()
        self._header_button.set_relief(Gtk.ReliefStyle.NONE)
        self._header_button.set_focus_on_click(False)
        self._header_button.get_style_context().add_class("tenga-logo-button")
        self._header_button.add(self._header_icon)
        self._header_button.connect("clicked", self._on_logo_clicked)
        header_box.pack_start(self._header_button, False, False, 0)
        main_box.pack_start(header_box, False, False, 5)

        # Status container
        status_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        status_container.set_halign(Gtk.Align.CENTER)
        status_container.set_margin_start(10)
        status_container.set_margin_end(10)
        status_container.set_margin_top(5)
        status_container.set_margin_bottom(5)

        # Connection status
        self._status_label = Gtk.Label(label="Отключено")
        self._status_label.get_style_context().add_class("status-disconnected")
        status_container.pack_start(self._status_label, False, False, 0)

        # Delay status
        delay_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        delay_container.set_halign(Gtk.Align.CENTER)
        delay_label_title = Gtk.Label(label="Задержка:")
        delay_label_title.set_halign(Gtk.Align.END)
        delay_container.pack_start(delay_label_title, False, False, 0)
        self._delay_label = Gtk.Label(label="—")
        self._delay_label.set_halign(Gtk.Align.START)
        delay_container.pack_start(self._delay_label, False, False, 0)
        status_container.pack_start(delay_container, False, False, 0)

        main_box.pack_start(status_container, False, False, 5)

        # Notebook with tabs
        self._monitoring_notebook = Gtk.Notebook()
        main_box.pack_start(self._monitoring_notebook, True, True, 0)

        # Tab 1: Profiles
        profiles_page = self._create_profiles_page()
        self._monitoring_notebook.append_page(profiles_page, Gtk.Label(label="Профили"))

        # Tab 2: Subscriptions
        subscriptions_page = self._create_subscriptions_page()
        self._monitoring_notebook.append_page(subscriptions_page, Gtk.Label(label="Подписки"))

        # Tab 3: Monitoring (only if monitoring is enabled)
        self._monitoring_page = self._create_monitoring_page()
        self._monitoring_page_index = self._monitoring_notebook.append_page(
            self._monitoring_page, Gtk.Label(label="Мониторинг")
        )
        self._update_monitoring_tab_visibility()

        # Connection buttons (outside notebook)
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(button_box, False, False, 10)

        self._connect_button = Gtk.Button(label="Подключить")
        self._connect_button.connect("clicked", self._on_connect_clicked)
        button_box.pack_start(self._connect_button, False, False, 0)

        refresh_button = Gtk.Button(label="Обновить")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        button_box.pack_start(refresh_button, False, False, 0)

        settings_button = Gtk.Button(label="Настройки")
        settings_button.set_tooltip_text("Настройки приложения")
        settings_button.connect("clicked", self._on_settings_clicked)
        button_box.pack_start(settings_button, False, False, 0)

        style_widget_tree(main_box)

    def _create_profiles_page(self) -> Gtk.Widget:
        """Create profiles page."""
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page_box.set_margin_start(5)
        page_box.set_margin_end(5)
        page_box.set_margin_top(5)
        page_box.set_margin_bottom(5)

        # Profile list
        profiles_label = Gtk.Label()
        profiles_label.set_markup("<b>Профили</b>")
        profiles_label.set_halign(Gtk.Align.START)
        page_box.pack_start(profiles_label, False, False, 0)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        page_box.pack_start(filter_box, False, False, 0)

        self._profile_filter_entry = Gtk.SearchEntry()
        self._profile_filter_entry.set_placeholder_text("Быстрый фильтр: имя, тип, сервер, группа")
        self._profile_filter_entry.connect("search-changed", self._on_profile_filter_changed)
        filter_box.pack_start(self._profile_filter_entry, True, True, 0)

        clear_filter_btn = Gtk.Button(label="Сброс")
        clear_filter_btn.set_tooltip_text("Очистить фильтр профилей")
        clear_filter_btn.connect("clicked", self._on_profile_filter_clear_clicked)
        filter_box.pack_start(clear_filter_btn, False, False, 0)

        # ScrolledWindow for list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(145)
        scrolled.set_max_content_height(235)
        self._profiles_stack = Gtk.Stack()
        self._profiles_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._profiles_stack.set_transition_duration(180)
        page_box.pack_start(self._profiles_stack, True, True, 0)

        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        self._profiles_empty_label = Gtk.Label(label="Профили не найдены")
        self._profiles_empty_label.get_style_context().add_class("dim-label")
        empty_box.pack_start(self._profiles_empty_label, False, False, 0)

        self._profiles_stack.add_named(scrolled, "list")
        self._profiles_stack.add_named(empty_box, "empty")
        self._profiles_stack.set_visible_child_name("list")
        self._profile_store = Gtk.TreeStore(bool, int, str, str, str, str, str)
        self._profile_list = Gtk.TreeView(model=self._profile_store)
        self._profile_list.set_headers_visible(True)
        self._profile_list.set_show_expanders(True)
        self._profile_list.set_level_indentation(20)
        # Columns
        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)

        col_name = Gtk.TreeViewColumn("Имя", renderer, text=2)
        col_name.set_expand(True)
        col_name.set_min_width(100)
        self._profile_list.append_column(col_name)

        self._col_type = Gtk.TreeViewColumn("Тип", renderer, text=3)
        self._col_type.set_min_width(70)
        self._col_type.set_clickable(True)
        self._col_type.connect("clicked", self._on_type_column_clicked)
        self._profile_list.append_column(self._col_type)

        col_addr = Gtk.TreeViewColumn("Сервер", renderer, text=4)
        col_addr.set_min_width(100)
        self._profile_list.append_column(col_addr)

        self._col_ping = Gtk.TreeViewColumn("Пинг", renderer, text=5)
        self._col_ping.set_min_width(80)
        self._col_ping.set_clickable(True)
        self._col_ping.connect("clicked", self._on_ping_column_clicked)
        self._profile_list.append_column(self._col_ping)

        # Settings icon column
        icon_renderer = Gtk.CellRendererPixbuf()
        col_settings = Gtk.TreeViewColumn("", icon_renderer, icon_name=6)
        col_settings.set_min_width(30)
        col_settings.set_max_width(30)
        self._profile_list.append_column(col_settings)

        self._profile_list.connect("row-activated", self._on_row_activated)
        self._profile_list.connect("button-press-event", self._on_profile_list_button_press)

        scrolled.add(self._profile_list)

        # Profile management buttons (original placement: below list)
        profile_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        profile_button_box.set_halign(Gtk.Align.CENTER)
        page_box.pack_start(profile_button_box, False, False, 0)

        add_button = Gtk.Button(label="Добавить")
        add_button.set_tooltip_text("Добавить профиль по share link")
        add_button.connect("clicked", self._on_add_clicked)
        profile_button_box.pack_start(add_button, False, False, 0)

        edit_button = Gtk.Button(label="Редактировать")
        edit_button.set_tooltip_text("Редактировать выбранный профиль")
        edit_button.connect("clicked", self._on_edit_profile_clicked)
        profile_button_box.pack_start(edit_button, False, False, 0)

        delete_button = Gtk.Button(label="Удалить")
        delete_button.set_tooltip_text("Удалить выбранный профиль")
        delete_button.connect("clicked", self._on_delete_profile_clicked)
        profile_button_box.pack_start(delete_button, False, False, 0)

        test_delay_btn = Gtk.Button(label="Тест задержки")
        test_delay_btn.set_tooltip_text("Проверить задержку до прокси-сервера")
        test_delay_btn.connect("clicked", self._on_test_delay_clicked)
        profile_button_box.pack_start(test_delay_btn, False, False, 0)

        # Ensure headers reflect initial sort state (none)
        self._update_sort_headers()
        return page_box

    def _update_sort_headers(self) -> None:
        """Update column titles according to current sort state."""
        if not self._col_type or not self._col_ping:
            return

        type_title = "Тип"
        ping_title = "Пинг"

        if self._profile_sort_key == "type":
            type_title += " ▲" if self._profile_sort_ascending else " ▼"
        elif self._profile_sort_key == "ping":
            ping_title += " ▲" if self._profile_sort_ascending else " ▼"

        self._col_type.set_title(type_title)
        self._col_ping.set_title(ping_title)

    def _on_type_column_clicked(self, column: Gtk.TreeViewColumn) -> None:
        """Handle click on 'Тип' header."""
        if self._profile_sort_key == "type":
            self._profile_sort_ascending = not self._profile_sort_ascending
        else:
            self._profile_sort_key = "type"
            self._profile_sort_ascending = True

        self._update_sort_headers()
        self._refresh_profiles()

    def _on_ping_column_clicked(self, column: Gtk.TreeViewColumn) -> None:
        """Handle click on 'Пинг' header."""
        if self._profile_sort_key == "ping":
            self._profile_sort_ascending = not self._profile_sort_ascending
        else:
            self._profile_sort_key = "ping"
            self._profile_sort_ascending = True

        self._update_sort_headers()
        self._refresh_profiles()

    def _create_monitoring_page(self) -> Gtk.Widget:
        """Create monitoring page."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(120)
        scrolled.set_max_content_height(190)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        page_box.set_margin_start(15)
        page_box.set_margin_end(15)
        page_box.set_margin_top(15)
        page_box.set_margin_bottom(15)

        # Title
        title_label = Gtk.Label()
        title_label.set_markup("<b>Мониторинг соединений</b>")
        title_label.set_halign(Gtk.Align.START)
        page_box.pack_start(title_label, False, False, 0)

        # Proxy status frame
        proxy_frame = Gtk.Frame()
        proxy_frame.set_label("Статус прокси")
        proxy_frame.set_margin_top(10)
        page_box.pack_start(proxy_frame, False, False, 0)

        proxy_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        proxy_box.set_margin_start(10)
        proxy_box.set_margin_end(10)
        proxy_box.set_margin_top(10)
        proxy_box.set_margin_bottom(10)
        proxy_frame.add(proxy_box)

        proxy_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        proxy_status_label = Gtk.Label(label="Статус:")
        proxy_status_label.set_halign(Gtk.Align.START)
        proxy_status_box.pack_start(proxy_status_label, False, False, 0)

        self._monitoring_proxy_status = Gtk.Label(label="—")
        self._monitoring_proxy_status.set_halign(Gtk.Align.START)
        self._monitoring_proxy_status.get_style_context().add_class("status-disconnected")
        proxy_status_box.pack_start(self._monitoring_proxy_status, False, False, 0)
        proxy_box.pack_start(proxy_status_box, False, False, 0)

        # VPN status frame
        vpn_frame = Gtk.Frame()
        vpn_frame.set_label("Статус VPN")
        vpn_frame.set_margin_top(10)
        page_box.pack_start(vpn_frame, False, False, 0)

        vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vpn_box.set_margin_start(10)
        vpn_box.set_margin_end(10)
        vpn_box.set_margin_top(10)
        vpn_box.set_margin_bottom(10)
        vpn_frame.add(vpn_box)

        vpn_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        vpn_status_label = Gtk.Label(label="Статус:")
        vpn_status_label.set_halign(Gtk.Align.START)
        vpn_status_box.pack_start(vpn_status_label, False, False, 0)

        self._monitoring_vpn_status = Gtk.Label(label="—")
        self._monitoring_vpn_status.set_halign(Gtk.Align.START)
        self._monitoring_vpn_status.get_style_context().add_class("status-disconnected")
        vpn_status_box.pack_start(self._monitoring_vpn_status, False, False, 0)
        vpn_box.pack_start(vpn_status_box, False, False, 0)

        routing_frame = Gtk.Frame()
        routing_frame.set_label("Маршрутизация (активный профиль)")
        routing_frame.set_margin_top(10)
        page_box.pack_start(routing_frame, False, False, 0)

        routing_grid = Gtk.Grid()
        routing_grid.set_row_spacing(4)
        routing_grid.set_column_spacing(10)
        routing_grid.set_margin_start(8)
        routing_grid.set_margin_end(8)
        routing_grid.set_margin_top(8)
        routing_grid.set_margin_bottom(8)
        routing_frame.add(routing_grid)

        routing_grid.attach(Gtk.Label(label="Режим:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._routing_mode_label = Gtk.Label(label="—")
        self._routing_mode_label.set_halign(Gtk.Align.START)
        routing_grid.attach(self._routing_mode_label, 1, 0, 1, 1)

        routing_grid.attach(Gtk.Label(label="DIRECT:", halign=Gtk.Align.END), 0, 1, 1, 1)
        self._routing_direct_status = Gtk.Label(label="—")
        self._routing_direct_status.set_halign(Gtk.Align.START)
        routing_grid.attach(self._routing_direct_status, 1, 1, 1, 1)

        routing_grid.attach(Gtk.Label(label="PROXY:", halign=Gtk.Align.END), 0, 2, 1, 1)
        self._routing_proxy_status = Gtk.Label(label="—")
        self._routing_proxy_status.set_halign(Gtk.Align.START)
        routing_grid.attach(self._routing_proxy_status, 1, 2, 1, 1)

        routing_grid.attach(Gtk.Label(label="VPN:", halign=Gtk.Align.END), 0, 3, 1, 1)
        self._routing_vpn_status = Gtk.Label(label="—")
        self._routing_vpn_status.set_halign(Gtk.Align.START)
        routing_grid.attach(self._routing_vpn_status, 1, 3, 1, 1)

        # Last check time
        last_check_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        last_check_label = Gtk.Label(label="Последняя проверка:")
        last_check_label.set_halign(Gtk.Align.START)
        last_check_box.pack_start(last_check_label, False, False, 0)

        self._monitoring_last_check = Gtk.Label(label="—")
        self._monitoring_last_check.set_halign(Gtk.Align.START)
        last_check_box.pack_start(self._monitoring_last_check, False, False, 0)
        page_box.pack_start(last_check_box, False, False, 10)

        # Refresh button
        refresh_monitoring_btn = Gtk.Button(label="Обновить сейчас")
        refresh_monitoring_btn.set_tooltip_text("Выполнить проверку соединений сейчас")
        refresh_monitoring_btn.connect("clicked", self._on_refresh_monitoring_clicked)
        page_box.pack_start(refresh_monitoring_btn, False, False, 0)

        # Info label
        info_label = Gtk.Label()
        info_label.set_markup(
            "<small>Мониторинг автоматически проверяет статус соединений "
            "с заданным интервалом. Уведомления отправляются при изменении статуса.</small>"
        )
        info_label.set_line_wrap(True)
        info_label.set_halign(Gtk.Align.START)
        info_label.set_margin_top(10)
        page_box.pack_start(info_label, False, False, 0)

        scrolled.add(page_box)
        return scrolled

    def _on_refresh_monitoring_clicked(self, button: Gtk.Button) -> None:
        """Refresh monitoring status manually."""
        # Trigger manual check if monitor is available
        monitor = self._context.monitor
        if monitor:
            monitor.check_now()

    def _create_subscriptions_page(self) -> Gtk.Widget:
        """Create subscriptions page."""
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page_box.set_margin_start(5)
        page_box.set_margin_end(5)
        page_box.set_margin_top(5)
        page_box.set_margin_bottom(5)

        subscriptions_label = Gtk.Label()
        subscriptions_label.set_markup("<b>Подписки</b>")
        subscriptions_label.set_halign(Gtk.Align.START)
        page_box.pack_start(subscriptions_label, False, False, 0)

        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        page_box.pack_start(filter_box, False, False, 0)

        self._subscription_filter_entry = Gtk.SearchEntry()
        self._subscription_filter_entry.set_placeholder_text("Быстрый фильтр: название, URL, дата")
        self._subscription_filter_entry.connect("search-changed", self._on_subscription_filter_changed)
        filter_box.pack_start(self._subscription_filter_entry, True, True, 0)

        clear_filter_btn = Gtk.Button(label="Сброс")
        clear_filter_btn.set_tooltip_text("Очистить фильтр подписок")
        clear_filter_btn.connect("clicked", self._on_subscription_filter_clear_clicked)
        filter_box.pack_start(clear_filter_btn, False, False, 0)

        sub_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        sub_button_box.set_halign(Gtk.Align.CENTER)
        page_box.pack_start(sub_button_box, False, False, 0)

        add_sub_button = Gtk.Button(label="Добавить подписку")
        add_sub_button.set_tooltip_text("Добавить новую подписку")
        add_sub_button.connect("clicked", self._on_add_subscription_clicked)
        sub_button_box.pack_start(add_sub_button, False, False, 0)

        update_sub_button = Gtk.Button(label="Обновить")
        update_sub_button.set_tooltip_text("Обновить выбранную подписку")
        update_sub_button.connect("clicked", self._on_update_subscription_clicked)
        sub_button_box.pack_start(update_sub_button, False, False, 0)

        edit_sub_button = Gtk.Button(label="Редактировать")
        edit_sub_button.set_tooltip_text("Редактировать выбранную подписку")
        edit_sub_button.connect("clicked", self._on_edit_subscription_clicked)
        sub_button_box.pack_start(edit_sub_button, False, False, 0)

        delete_sub_button = Gtk.Button(label="Удалить")
        delete_sub_button.set_tooltip_text("Удалить выбранную подписку")
        delete_sub_button.connect("clicked", self._on_delete_subscription_clicked)
        sub_button_box.pack_start(delete_sub_button, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(110)
        scrolled.set_max_content_height(170)
        self._subscriptions_stack = Gtk.Stack()
        self._subscriptions_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._subscriptions_stack.set_transition_duration(180)
        page_box.pack_start(self._subscriptions_stack, True, True, 0)

        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)
        self._subscriptions_empty_label = Gtk.Label(label="Подписки не найдены")
        self._subscriptions_empty_label.get_style_context().add_class("dim-label")
        empty_box.pack_start(self._subscriptions_empty_label, False, False, 0)

        self._subscriptions_stack.add_named(scrolled, "list")
        self._subscriptions_stack.add_named(empty_box, "empty")
        self._subscriptions_stack.set_visible_child_name("list")

        self._subscription_store = Gtk.ListStore(int, str, str, str, int)
        self._subscription_list = Gtk.TreeView(model=self._subscription_store)
        self._subscription_list.set_headers_visible(True)

        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)

        col_name = Gtk.TreeViewColumn("Название", renderer, text=1)
        col_name.set_expand(True)
        col_name.set_min_width(150)
        self._subscription_list.append_column(col_name)

        col_url = Gtk.TreeViewColumn("URL", renderer, text=2)
        col_url.set_min_width(200)
        self._subscription_list.append_column(col_url)

        col_updated = Gtk.TreeViewColumn("Обновлено", renderer, text=3)
        col_updated.set_min_width(150)
        self._subscription_list.append_column(col_updated)

        col_count = Gtk.TreeViewColumn("Профилей", renderer, text=4)
        col_count.set_min_width(80)
        self._subscription_list.append_column(col_count)

        self._subscription_list.connect("row-activated", self._on_subscription_row_activated)
        self._subscription_list.connect(
            "button-press-event", self._on_subscription_list_button_press
        )

        scrolled.add(self._subscription_list)

        return page_box

    def _run_profile_latency_test(self, profile_id: int) -> int:
        """
        Run profile latency test via app-level callback.

        Returns:
            Latency in milliseconds, or -1 on error.
        """
        if self._on_test_latency is None:
            return -1

        try:
            return int(self._on_test_latency(profile_id))
        except Exception:
            return -1

    def _format_ping_text(self, latency_ms: int) -> str:
        """Format latency value for display."""
        if latency_ms == -2:
            return "..."
        elif latency_ms >= 0:
            return f"{latency_ms} ms"
        else:
            return "—"

    def _find_profile_iter(self, store: Gtk.TreeStore, profile_id: int, parent: Gtk.TreeIter | None = None) -> Gtk.TreeIter | None:
        """
        Find TreeIter for profile with given ID in the tree.

        Args:
            store: TreeStore to search in
            profile_id: Profile ID to find
            parent: Parent iterator (None for root level)

        Returns:
            TreeIter if found, None otherwise
        """
        iter = store.iter_children(parent) if parent else store.get_iter_first()
        while iter:
            is_group = store[iter][0]
            item_id = store[iter][1]

            if not is_group and item_id == profile_id:
                return iter

            # Check children if it's a group
            if is_group:
                child_iter = self._find_profile_iter(store, profile_id, iter)
                if child_iter:
                    return child_iter

            iter = store.iter_next(iter)

        return None

    def _update_profile_ping_in_ui(self, profile_id: int, latency_ms: int) -> None:
        """Update ping value for a profile in the UI tree."""
        if not self._profile_store:
            return

        iter = self._find_profile_iter(self._profile_store, profile_id)
        if iter:
            ping_text = self._format_ping_text(latency_ms)
            self._profile_store[iter][5] = ping_text

    def _on_test_delay_clicked(self, button: Gtk.Button | None) -> None:
        """Test profile or group latency."""
        profile_id = self._get_selected_profile_id()
        group_id = self._get_selected_group_id()

        if profile_id is not None:
            profile = self._context.profiles.get_profile(profile_id)
            if not profile:
                return

            self._delay_label.set_text("...")
            self._update_profile_ping_in_ui(profile_id, -2)

            def do_test():
                latency_ms = self._run_profile_latency_test(profile_id)
                profile.latency_ms = latency_ms
                self._context.profiles.save()

                GLib.idle_add(self._update_profile_ping_in_ui, profile_id, latency_ms)
                GLib.idle_add(self._show_delay_result, latency_ms)

            thread = threading.Thread(target=do_test, daemon=True)
            thread.start()

        elif group_id is not None:
            group = self._context.profiles.get_group(group_id)
            if not group:
                return

            profiles = self._context.profiles.get_profiles_in_group(group_id)
            if not profiles:
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Группа пуста",
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text("В группе нет профилей для тестирования.")
                dialog.run()
                dialog.destroy()
                return

            self._delay_label.set_text(f"Тестирование {len(profiles)} профилей...")

            for profile in profiles:
                self._update_profile_ping_in_ui(profile.id, -2)

            def test_profile(profile_id: int) -> None:
                """Test single profile and update UI."""
                latency_ms = self._run_profile_latency_test(profile_id)
                profile = self._context.profiles.get_profile(profile_id)
                if profile:
                    profile.latency_ms = latency_ms

                GLib.idle_add(self._update_profile_ping_in_ui, profile_id, latency_ms)

            def test_all_profiles():
                """Test all profiles asynchronously."""
                threads = []
                for profile in profiles:
                    thread = threading.Thread(
                        target=test_profile, args=(profile.id,), daemon=True
                    )
                    thread.start()
                    threads.append(thread)

                # Wait for all threads to complete
                for thread in threads:
                    thread.join()

                self._context.profiles.save()
                GLib.idle_add(self._delay_label.set_text, "Готово")

            thread = threading.Thread(target=test_all_profiles, daemon=True)
            thread.start()

        else:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите профиль или группу",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text("Выберите профиль или группу для тестирования задержки.")
            dialog.run()
            dialog.destroy()

    def _show_delay_result(self, delay: int) -> None:
        """Show delay test result."""
        ctx = self._delay_label.get_style_context()
        ctx.remove_class("delay-good")
        ctx.remove_class("delay-medium")
        ctx.remove_class("delay-bad")

        if delay < 0:
            self._delay_label.set_text("Ошибка")
            ctx.add_class("delay-bad")
        else:
            self._delay_label.set_text(f"{delay} ms")
            if delay < 200:
                ctx.add_class("delay-good")
            elif delay < 500:
                ctx.add_class("delay-medium")
            else:
                ctx.add_class("delay-bad")

    def _on_profile_filter_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle live filtering of profile tree."""
        self._refresh_profiles()

    def _on_profile_filter_clear_clicked(self, button: Gtk.Button) -> None:
        """Clear profile filter text."""
        if self._profile_filter_entry:
            self._profile_filter_entry.set_text("")
            self._profile_filter_entry.grab_focus()

    def _on_subscription_filter_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle live filtering of subscriptions list."""
        self._refresh_subscriptions()

    def _on_subscription_filter_clear_clicked(self, button: Gtk.Button) -> None:
        """Clear subscription filter text."""
        if self._subscription_filter_entry:
            self._subscription_filter_entry.set_text("")
            self._subscription_filter_entry.grab_focus()

    def _update_profiles_empty_state(self, has_rows: bool, query: str) -> None:
        """Toggle profiles list placeholder."""
        if not self._profiles_stack or not self._profiles_empty_label:
            return
        if has_rows:
            self._profiles_stack.set_visible_child_name("list")
            return

        if query:
            self._profiles_empty_label.set_text("Ничего не найдено по фильтру профилей")
        else:
            self._profiles_empty_label.set_text("Профилей пока нет. Добавьте первый профиль.")
        self._profiles_stack.set_visible_child_name("empty")

    def _update_subscriptions_empty_state(self, has_rows: bool, query: str) -> None:
        """Toggle subscriptions list placeholder."""
        if not self._subscriptions_stack or not self._subscriptions_empty_label:
            return
        if has_rows:
            self._subscriptions_stack.set_visible_child_name("list")
            return

        if query:
            self._subscriptions_empty_label.set_text("Ничего не найдено по фильтру подписок")
        else:
            self._subscriptions_empty_label.set_text("Подписок пока нет. Добавьте первую подписку.")
        self._subscriptions_stack.set_visible_child_name("empty")

    def _refresh_profiles(self) -> None:
        """Refresh profile list with hierarchical structure (groups -> profiles)."""
        if not self._profile_store or not self._profile_list:
            return

        self._profile_store.clear()
        query = ""
        if self._profile_filter_entry:
            query = self._profile_filter_entry.get_text().strip().lower()
        has_visible_rows = False

        groups = self._context.profiles.groups
        current_profile_id = self._context.proxy_state.started_profile_id

        sorted_groups = sorted(
            groups.values(), key=lambda g: (not g.is_subscription, g.name.lower())
        )

        for group in sorted_groups:
            if group.is_subscription:
                group_icon = "network-server-symbolic"
                group_prefix = "📡 "
            else:
                group_icon = "folder-symbolic"
                group_prefix = "📁 "

            group_profiles = list(self._context.profiles.get_profiles_in_group(group.id))

            if query:
                group_match = query in group.name.lower()
                if group_match:
                    visible_profiles = list(group_profiles)
                else:
                    visible_profiles = []
                    for profile in group_profiles:
                        if (
                            query in profile.name.lower()
                            or query in (profile.proxy_type or "").lower()
                            or query in profile.bean.display_address.lower()
                        ):
                            visible_profiles.append(profile)
                if not visible_profiles:
                    continue
            else:
                visible_profiles = list(group_profiles)

            group_iter = self._profile_store.append(
                None,
                [
                    True,  # is_group
                    group.id,
                    f"{group_prefix}{group.name} ({len(visible_profiles)})",  # name
                    "Группа",
                    "",
                    "",  # ping
                    group_icon,
                ],
            )
            has_visible_rows = True

            # Apply sorting inside group if needed
            if self._profile_sort_key == "type":
                visible_profiles.sort(
                    key=lambda p: (p.proxy_type or "").lower(),
                    reverse=not self._profile_sort_ascending,
                )
            elif self._profile_sort_key == "ping":
                def _ping_key(profile: object) -> tuple[int, int]:
                    latency = getattr(profile, "latency_ms", -1)
                    if latency is None:
                        latency = -1
                    return (1 if latency < 0 else 0, latency if latency >= 0 else 0)

                visible_profiles.sort(
                    key=_ping_key,
                    reverse=not self._profile_sort_ascending,
                )

            for profile in visible_profiles:
                name = profile.name
                if profile.id == current_profile_id:
                    name = f"✓ {name}"

                if profile.latency_ms >= 0:
                    ping_text = f"{profile.latency_ms} ms"
                else:
                    ping_text = "—"

                self._profile_store.append(
                    group_iter,
                    [
                        False,  # is_group
                        profile.id,
                        name,
                        profile.proxy_type.upper(),
                        profile.bean.display_address,
                        ping_text,
                        "preferences-system-symbolic",
                    ],
                )
                has_visible_rows = True

        # Expand and scroll to active profile
        if current_profile_id is not None:
            profile_iter = self._find_profile_iter(self._profile_store, current_profile_id)
            if profile_iter:
                path = self._profile_store.get_path(profile_iter)
                if path:
                    self._profile_list.expand_to_path(path)
                    self._profile_list.scroll_to_cell(path, None, True, 0.5, 0.0)
        else:
            # Expand subscription groups by default
            for group in sorted_groups:
                if group.is_subscription:
                    group_iter = self._profile_store.iter_children(None)
                    while group_iter:
                        if self._profile_store[group_iter][1] == group.id:
                            path = self._profile_store.get_path(group_iter)
                            self._profile_list.expand_row(path, False)
                            break
                        group_iter = self._profile_store.iter_next(group_iter)

        self._update_profiles_empty_state(has_visible_rows, query)

    def _refresh_subscriptions(self) -> None:
        """Refresh subscriptions list."""
        if not self._subscription_store:
            return

        self._subscription_store.clear()
        query = ""
        if self._subscription_filter_entry:
            query = self._subscription_filter_entry.get_text().strip().lower()
        has_visible_rows = False

        groups = self._context.profiles.groups
        for group in groups.values():
            if not group.is_subscription:
                continue
            if group.last_updated > 0:
                update_time = datetime.datetime.fromtimestamp(group.last_updated)
                updated_str = update_time.strftime("%d.%m.%Y %H:%M")
            else:
                updated_str = "Никогда"

            profile_count = len(
                self._context.profiles.get_profiles_in_group(group.id)
            )

            url_display = group.subscription_url
            if len(url_display) > 50:
                url_display = url_display[:47] + "..."

            if query and (
                query not in group.name.lower()
                and query not in group.subscription_url.lower()
                and query not in updated_str.lower()
            ):
                continue

            self._subscription_store.append(
                [
                    group.id,
                    group.name,
                    url_display,
                    updated_str,
                    profile_count,
                ]
            )
            has_visible_rows = True

        self._update_subscriptions_empty_state(has_visible_rows, query)

    def _get_selected_subscription_id(self) -> int | None:
        """Get selected subscription group ID."""
        if not self._subscription_list:
            return None
        selection = self._subscription_list.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            return model[treeiter][0]
        return None

    def _on_subscription_row_activated(
        self, tree_view: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn
    ) -> None:
        """Double click on subscription - update it."""
        self._on_update_subscription_clicked(None)

    def _on_subscription_list_button_press(
        self, tree_view: Gtk.TreeView, event: Gdk.EventButton
    ) -> bool:
        """Handle button press on subscription list."""
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            path_info = tree_view.get_path_at_pos(int(event.x), int(event.y))
            if not path_info:
                return False

            path, _column, _cell_x, _cell_y = path_info
            selection = tree_view.get_selection()
            selection.unselect_all()
            selection.select_path(path)
            tree_view.grab_focus()

            menu = Gtk.Menu()

            update_item = Gtk.MenuItem(label="Обновить")
            update_item.connect("activate", lambda *_: self._on_update_subscription_clicked(None))
            menu.append(update_item)

            edit_item = Gtk.MenuItem(label="Редактировать")
            edit_item.connect("activate", lambda *_: self._on_edit_subscription_clicked(None))
            menu.append(edit_item)

            delete_item = Gtk.MenuItem(label="Удалить")
            delete_item.connect("activate", lambda *_: self._on_delete_subscription_clicked(None))
            menu.append(delete_item)

            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)
            return True

        return False

    def _on_add_subscription_clicked(self, button: Gtk.Button) -> None:
        """Click on Add Subscription button."""
        result = show_subscription_dialog(self)

        if result:
            name, url = result
            group = self._context.profiles.add_group(name, is_subscription=True)
            group.subscription_url = url
            self._update_subscription(group.id)

    def _on_update_subscription_clicked(self, button: Gtk.Button | None) -> None:
        """Click on Update Subscription button."""
        group_id = self._get_selected_subscription_id()

        if group_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите подписку",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text("Выберите подписку для обновления.")
            dialog.run()
            dialog.destroy()
            return

        self._update_subscription(group_id)

    def _update_subscription(self, group_id: int) -> None:
        """Update subscription."""
        group = self._context.profiles.get_group(group_id)
        if not group or not group.is_subscription:
            return

        progress_dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Обновление подписки...",
        )
        progress_dialog.set_wmclass("tenga-proxy", "tenga-proxy")
        progress_dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        progress_dialog.set_skip_taskbar_hint(True)
        progress_dialog.format_secondary_text(f"Загрузка подписки: {group.name}")
        progress_dialog.show()

        def do_update():
            """Update subscription in background thread."""
            try:
                updater = SubscriptionUpdater(
                    config=self._context.config, profiles=self._context.profiles
                )

                beans = updater.update(
                    group.subscription_url,
                    group_id=group_id,
                    clear_existing=True,
                )
                group.last_updated = int(time.time())
                self._context.profiles.save()

                GLib.idle_add(
                    lambda: self._show_update_result(
                        progress_dialog, True, len(beans), group.name
                    )
                )
            except Exception as e:
                GLib.idle_add(
                    lambda: self._show_update_result(progress_dialog, False, 0, group.name, str(e))
                )

        thread = threading.Thread(target=do_update, daemon=True)
        thread.start()

    def _show_update_result(
        self,
        progress_dialog: Gtk.Dialog,
        success: bool,
        count: int,
        name: str,
        error: str = "",
    ) -> None:
        """Show subscription update result."""
        progress_dialog.destroy()

        if success:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Подписка обновлена",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text(f"Подписка '{name}' обновлена.\nДобавлено профилей: {count}")
            dialog.run()
            dialog.destroy()

            self._refresh_subscriptions()
            self._refresh_profiles()
        else:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Ошибка обновления подписки",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text(f"Не удалось обновить подписку '{name}'.\n\nОшибка: {error}")
            dialog.run()
            dialog.destroy()

    def _on_edit_subscription_clicked(self, button: Gtk.Button | None) -> None:
        """Click on Edit Subscription button."""
        group_id = self._get_selected_subscription_id()

        if group_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите подписку",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text("Выберите подписку для редактирования.")
            dialog.run()
            dialog.destroy()
            return

        group = self._context.profiles.get_group(group_id)
        if not group:
            return

        result = show_subscription_dialog(self, group)

        if result:
            name, url = result
            group.name = name
            group.subscription_url = url
            self._context.profiles.save()
            self._refresh_subscriptions()

    def _on_delete_subscription_clicked(self, button: Gtk.Button | None) -> None:
        """Click on Delete Subscription button."""
        group_id = self._get_selected_subscription_id()

        if group_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите подписку",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text("Выберите подписку для удаления.")
            dialog.run()
            dialog.destroy()
            return

        group = self._context.profiles.get_group(group_id)
        if not group:
            return

        profile_count = len(self._context.profiles.get_profiles_in_group(group_id))

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Удалить подписку?",
        )
        dialog.set_wmclass("tenga-proxy", "tenga-proxy")
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dialog.set_skip_taskbar_hint(True)
        dialog.format_secondary_text(
            f"Удалить подписку '{group.name}'?\n\n"
            f"Будет удалено профилей: {profile_count}\n"
            f"Это действие нельзя отменить."
        )
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self._context.profiles.remove_group(group_id, remove_profiles=True)
            self._context.profiles.save()
            self._refresh_subscriptions()
            self._refresh_profiles()

    def _on_state_changed(self, state: ProxyState) -> None:
        """State change handler."""
        GLib.idle_add(self._update_ui, state)

    def _load_logo_pixbufs(self) -> None:
        """Load color and grayscale versions of the inner logo."""
        from src.core.config import get_asset_path

        logo_path = get_asset_path("logo_inner.png")
        if not logo_path.exists():
            return
        try:
            color = GdkPixbuf.Pixbuf.new_from_file_at_size(str(logo_path), 192, 192)
            gray = color.copy()
            color.saturate_and_pixelate(gray, 0.0, False)
            self._logo_color = color
            self._logo_gray = gray
        except Exception:
            self._logo_color = None
            self._logo_gray = None

    def _update_logo_state(self, state: ProxyState) -> None:
        """Update logo button image, sensitivity and tooltip based on state."""
        if not self._header_button or not self._header_icon:
            return

        ctx = self._header_button.get_style_context()

        if self._connecting:
            if self._logo_gray is not None:
                self._header_icon.set_from_pixbuf(self._logo_gray)
            self._header_button.set_sensitive(False)
            ctx.add_class("tenga-logo-pulse")
            self._header_button.set_tooltip_text("Подключение...")
            return

        ctx.remove_class("tenga-logo-pulse")

        if state.is_running:
            if self._logo_color is not None:
                self._header_icon.set_from_pixbuf(self._logo_color)
            self._header_button.set_sensitive(True)
            profile = self._context.profiles.get_profile(state.started_profile_id)
            name = profile.name if profile else "..."
            self._header_button.set_tooltip_text(f"Отключиться от: {name}")
        else:
            if self._logo_gray is not None:
                self._header_icon.set_from_pixbuf(self._logo_gray)
            self._header_button.set_sensitive(True)
            sel_id = self._get_selected_profile_id()
            if sel_id is not None:
                profile = self._context.profiles.get_profile(sel_id)
                name = profile.name if profile else "..."
                self._header_button.set_tooltip_text(f"Подключиться к: {name}")
            else:
                self._header_button.set_tooltip_text("Выберите профиль")

    def _on_logo_clicked(self, button: Gtk.Button) -> None:
        """Click on logo - same as connect/disconnect button."""
        was_running = self._context.proxy_state.is_running
        will_act = was_running or self._get_selected_profile_id() is not None
        if will_act:
            self._connecting = True
            self._update_logo_state(self._context.proxy_state)
        self._on_connect_clicked(button)

    def _update_ui(self, state: ProxyState) -> None:
        """Update UI."""
        # State change ends any in-progress connecting animation
        self._connecting = False
        if state.is_running:
            profile = self._context.profiles.get_profile(state.started_profile_id)
            name = profile.name if profile else "Unknown"

            self._status_label.set_justify(Gtk.Justification.CENTER)
            self._status_label.set_text(f"Подключено\n{name}")
            self._status_label.get_style_context().remove_class("status-disconnected")
            self._status_label.get_style_context().add_class("status-connected")

            self._connect_button.set_label("Отключить")
        else:
            self._status_label.set_text("Отключено")
            self._status_label.get_style_context().remove_class("status-connected")
            self._status_label.get_style_context().add_class("status-disconnected")

            self._connect_button.set_label("Подключить")
            if self._delay_label:
                self._delay_label.set_text("—")
                ctx = self._delay_label.get_style_context()
                ctx.remove_class("delay-good")
                ctx.remove_class("delay-medium")
                ctx.remove_class("delay-bad")

        self._update_logo_state(state)
        self._update_routing_indicators(state)
        self._refresh_profiles()

    def _update_routing_indicators(self, state: ProxyState) -> None:
        """Update routing indicators for active profile."""
        if (
            not self._routing_mode_label
            or not self._routing_direct_status
            or not self._routing_proxy_status
            or not self._routing_vpn_status
        ):
            return

        if not state.is_running:
            self._routing_mode_label.set_text("—")
            self._routing_direct_status.set_text("—")
            self._routing_proxy_status.set_text("—")
            self._routing_vpn_status.set_text("—")
            return

        profile = self._context.profiles.get_profile(state.started_profile_id)
        if not profile:
            self._routing_mode_label.set_text("Профиль не найден")
            self._routing_direct_status.set_text("—")
            self._routing_proxy_status.set_text("—")
            self._routing_vpn_status.set_text("—")
            return

        routing = profile.routing_settings
        if routing is None:
            routing = self._context.config.routing
            if routing.mode == RoutingMode.CUSTOM:
                routing.load_lists_from_files(self._context.config_dir)

        mode_text = (
            "PROXY_ALL"
            if routing.mode == RoutingMode.PROXY_ALL
            else "CUSTOM"
        )
        self._routing_mode_label.set_text(mode_text)

        if routing.mode == RoutingMode.PROXY_ALL:
            direct_status = (
                "активен (bypass local)"
                if routing.bypass_local_networks
                else "не задан"
            )
            proxy_status = "активен (весь трафик)"
            vpn_status = "не задан"
        else:
            direct_rules_count = len(routing.direct_list or [])
            if routing.bypass_local_networks:
                direct_rules_count += 1

            direct_status = (
                f"активен ({direct_rules_count} правил)"
                if direct_rules_count > 0
                else "не задан"
            )

            proxy_rules_count = len(routing.proxy_list or [])
            if proxy_rules_count > 0:
                proxy_status = f"активен ({proxy_rules_count} правил + default)"
            else:
                proxy_status = "активен (default)"

            vpn_rules_count = len(routing.vpn_list or [])
            vpn_settings = profile.vpn_settings
            vpn_enabled = bool(vpn_settings and vpn_settings.enabled and vpn_settings.connection_name)
            vpn_is_up = bool(
                vpn_enabled
                and vpn_settings is not None
                and is_vpn_active(vpn_settings.connection_name)
            )

            if vpn_rules_count == 0:
                vpn_status = "не задан"
            elif vpn_is_up:
                vpn_status = f"активен ({vpn_rules_count} правил)"
            elif vpn_enabled:
                vpn_status = f"правила есть ({vpn_rules_count}), VPN не активен"
            else:
                vpn_status = f"правила есть ({vpn_rules_count}), VPN выключен"

        self._routing_direct_status.set_text(direct_status)
        self._routing_proxy_status.set_text(proxy_status)
        self._routing_vpn_status.set_text(vpn_status)

    def _get_selected_profile_id(self) -> int | None:
        """Get selected profile ID (returns None if group is selected)."""
        selection = self._profile_list.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            is_group = model[treeiter][0]
            profile_id = model[treeiter][1]
            if not is_group:
                return profile_id
        return None

    def _get_selected_group_id(self) -> int | None:
        """Get selected group ID (returns None if profile is selected)."""
        selection = self._profile_list.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            is_group = model[treeiter][0]
            group_id = model[treeiter][1]
            if is_group:
                return group_id
        return None

    def _on_row_activated(
        self, tree_view: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn
    ) -> None:
        """Double click on profile or group."""
        model = tree_view.get_model()
        treeiter = model.get_iter(path)
        is_group = model[treeiter][0]
        item_id = model[treeiter][1]

        if is_group:
            if tree_view.row_expanded(path):
                tree_view.collapse_row(path)
            else:
                tree_view.expand_row(path, False)
        else:
            if self._on_connect:
                self._on_connect(item_id)

    def _on_profile_list_button_press(
        self, tree_view: Gtk.TreeView, event: Gdk.EventButton
    ) -> bool:
        """Handle button press on profile list."""
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            path_info = tree_view.get_path_at_pos(int(event.x), int(event.y))
            if not path_info:
                return False

            path, _column, _cell_x, _cell_y = path_info
            selection = tree_view.get_selection()
            selection.unselect_all()
            selection.select_path(path)
            tree_view.grab_focus()

            model = tree_view.get_model()
            treeiter = model.get_iter(path)
            is_group = model[treeiter][0]
            item_id = model[treeiter][1]

            menu = Gtk.Menu()

            if is_group:
                if tree_view.row_expanded(path):
                    expand_item = Gtk.MenuItem(label="Свернуть группу")
                    expand_item.connect("activate", lambda *_: tree_view.collapse_row(path))
                else:
                    expand_item = Gtk.MenuItem(label="Развернуть группу")
                    expand_item.connect("activate", lambda *_: tree_view.expand_row(path, False))
                menu.append(expand_item)

                test_item = Gtk.MenuItem(label="Тест задержки")
                test_item.connect("activate", lambda *_: self._on_test_delay_clicked(None))
                menu.append(test_item)
            else:
                connect_item = Gtk.MenuItem(label="Подключить")
                connect_item.connect("activate", lambda *_: self._on_connect and self._on_connect(item_id))
                menu.append(connect_item)

                vpn_item = Gtk.MenuItem(label="VPN и маршруты...")
                vpn_item.connect("activate", lambda *_: self._open_profile_vpn_settings(item_id))
                menu.append(vpn_item)

                test_item = Gtk.MenuItem(label="Тест задержки")
                test_item.connect("activate", lambda *_: self._on_test_delay_clicked(None))
                menu.append(test_item)

            menu.append(Gtk.SeparatorMenuItem())

            edit_item = Gtk.MenuItem(label="Редактировать")
            edit_item.connect("activate", lambda *_: self._on_edit_profile_clicked(None))
            menu.append(edit_item)

            delete_item = Gtk.MenuItem(label="Удалить")
            delete_item.connect("activate", lambda *_: self._on_delete_profile_clicked(None))
            menu.append(delete_item)

            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)
            return True

        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 1:
            return False

        path_info = tree_view.get_path_at_pos(int(event.x), int(event.y))
        if not path_info:
            return False

        path, column, cell_x, cell_y = path_info

        columns = tree_view.get_columns()
        if column == columns[-1]:
            model = tree_view.get_model()
            treeiter = model.get_iter(path)
            is_group = model[treeiter][0]
            item_id = model[treeiter][1]

            if not is_group:
                self._open_profile_vpn_settings(item_id)
                return True

        return False

    def _open_profile_vpn_settings(self, profile_id: int) -> None:
        """Open VPN settings dialog for profile and refresh list."""
        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            return

        def on_settings_applied(edited_profile_id: int) -> None:
            """Reload configuration if edited profile is currently active."""
            if (
                self._context.proxy_state.is_running
                and self._context.proxy_state.started_profile_id == edited_profile_id
                and self._on_config_reload
            ):
                try:
                    self._on_config_reload()
                except Exception:
                    pass

        show_profile_vpn_settings_dialog(profile, self, on_settings_applied=on_settings_applied)
        self._context.profiles.save()
        self._refresh_profiles()

    def _on_connect_clicked(self, button: Gtk.Button) -> None:
        """Click on Connect/Disconnect button."""
        if self._context.proxy_state.is_running:
            if self._on_disconnect:
                self._on_disconnect()
        else:
            profile_id = self._get_selected_profile_id()
            if profile_id is not None and self._on_connect:
                self._on_connect(profile_id)
            else:
                group_id = self._get_selected_group_id()
                if group_id is not None:
                    dialog = Gtk.MessageDialog(
                        transient_for=self,
                        flags=0,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.OK,
                        text="Выбрана группа",
                    )
                    dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                    dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                    dialog.set_skip_taskbar_hint(True)
                    dialog.format_secondary_text(
                        "Выбрана группа. Выберите конкретный профиль для подключения."
                    )
                    dialog.run()
                    dialog.destroy()
                else:
                    dialog = Gtk.MessageDialog(
                        transient_for=self,
                        flags=0,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.OK,
                        text="Выберите профиль",
                    )
                    dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                    dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                    dialog.set_skip_taskbar_hint(True)
                    dialog.format_secondary_text("Выберите профиль из списка для подключения.")
                    dialog.run()
                    dialog.destroy()

    def _on_refresh_clicked(self, button: Gtk.Button) -> None:
        """Click on Refresh button."""
        self._refresh_profiles()

    def _on_add_clicked(self, button: Gtk.Button) -> None:
        """Click on Add button."""
        from src.ui.dialogs import show_add_profile_dialog

        profile = show_add_profile_dialog(self)

        if profile:
            # Add profile
            entry = self._context.profiles.add_profile(profile)
            self._context.profiles.save()
            # Update list
            self._refresh_profiles()
            # Show notification
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Профиль добавлен",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text(f"{entry.name}\n{profile.display_address}")
            dialog.run()
            dialog.destroy()

    def _on_delete_profile_clicked(self, button: Gtk.Button | None) -> None:
        """Click on Delete button."""
        profile_id = self._get_selected_profile_id()
        group_id = self._get_selected_group_id()

        if profile_id is None and group_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите профиль или группу",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text("Выберите профиль или группу для удаления.")
            dialog.run()
            dialog.destroy()
            return

        # Check for active connection
        if self._context.proxy_state.is_running:
            active_profile_id = self._context.proxy_state.started_profile_id
            if (profile_id is not None and profile_id == active_profile_id) or (
                group_id is not None
                and active_profile_id in [
                    p.id for p in self._context.profiles.get_profiles_in_group(group_id)
                ]
            ):
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Нельзя удалить активный профиль или группу",
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text(
                    "Сначала отключитесь, а затем повторите попытку."
                )
                dialog.run()
                dialog.destroy()
                return

        if group_id is not None:
            group = self._context.profiles.get_group(group_id)
            if not group:
                return

            if group.is_subscription:
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Нельзя удалить группу от подписки",
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text(
                    "Для удаления группы, созданной подпиской, удалите саму подписку на вкладке 'Подписки'."
                )
                dialog.run()
                dialog.destroy()
                return

            profile_count = len(self._context.profiles.get_profiles_in_group(group_id))
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Удалить группу?",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text(
                f"Удалить группу '{group.name}'?\n\n"
                f"Будет удалено профилей: {profile_count}\n"
                f"Это действие нельзя отменить."
            )
            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.YES:
                self._context.profiles.remove_group(group_id, remove_profiles=True)
                self._context.profiles.save()
                self._refresh_profiles()
            return

        if profile_id is not None:
            profile = self._context.profiles.get_profile(profile_id)
            if not profile:
                return

            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Удалить профиль?",
            )
            dialog.set_wmclass("tenga-proxy", "tenga-proxy")
            dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            dialog.set_skip_taskbar_hint(True)
            dialog.format_secondary_text(f"Удалить профиль '{profile.name}'?")
            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.YES:
                self._context.profiles.remove_profile(profile_id)
                self._context.profiles.save()
                self._refresh_profiles()

    def _on_edit_profile_clicked(self, button: Gtk.Button | None) -> None:
        """Click on Edit button."""
        profile_id = self._get_selected_profile_id()

        if profile_id is not None:
            profile = self._context.profiles.get_profile(profile_id)
            if not profile:
                return

            changed = show_edit_profile_dialog(profile, self)
            if changed:
                self._context.profiles.save()
                self._refresh_profiles()
            return

        group_id = self._get_selected_group_id()
        if group_id is not None:
            group = self._context.profiles.get_group(group_id)
            if not group:
                return
            if group.is_subscription:
                result = show_subscription_dialog(self, group)
                if result:
                    name, url = result
                    group.name = name
                    group.subscription_url = url
                    self._context.profiles.save()
                    self._refresh_profiles()
                    self._refresh_subscriptions()
            else:
                new_name = show_edit_group_dialog(self, group)
                if new_name:
                    group.name = new_name
                    self._context.profiles.save()
                    self._refresh_profiles()
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="Выберите профиль или группу",
        )
        dialog.set_wmclass("tenga-proxy", "tenga-proxy")
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dialog.set_skip_taskbar_hint(True)
        dialog.format_secondary_text("Выберите профиль или группу для редактирования.")
        dialog.run()
        dialog.destroy()

    def _on_settings_clicked(self, button: Gtk.Button) -> None:
        """Click on Settings button."""
        from src.ui.dialogs import show_settings_dialog

        show_settings_dialog(self._context, self, on_config_reload=self._on_config_reload)

    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Handle window realization - set WM_CLASS via Gdk.Window."""
        window = self.get_window()
        if window:
            # Set WM_CLASS directly via Gdk.Window for better compatibility
            try:
                window.set_wmclass("tenga-proxy", "tenga-proxy")
            except Exception:
                pass

            GLib.idle_add(self._restore_or_fit_to_workarea)

    def _restore_or_fit_to_workarea(self) -> bool:
        """Restore saved geometry or fit and center window within monitor workarea."""
        gdk_window = self.get_window()
        if not gdk_window:
            return False

        try:
            screen = gdk_window.get_screen()
            monitor_index = screen.get_monitor_at_window(gdk_window)
            workarea = screen.get_monitor_workarea(monitor_index)

            max_width = max(360, workarea.width - 24)
            max_height = max(340, workarea.height - 24)

            target_width = min(max(350, self._saved_width), max_width)
            target_height = min(max(340, self._saved_height), max_height)
            self.resize(target_width, target_height)

            if self._saved_x is not None and self._saved_y is not None:
                min_x = workarea.x
                max_x = workarea.x + max(0, workarea.width - target_width)
                min_y = workarea.y
                max_y = workarea.y + max(0, workarea.height - target_height)
                target_x = min(max(self._saved_x, min_x), max_x)
                target_y = min(max(self._saved_y, min_y), max_y)
                self.move(target_x, target_y)
                self._saved_x = target_x
                self._saved_y = target_y
            else:
                x = workarea.x + max(0, (workarea.width - target_width) // 2)
                y = workarea.y + max(0, (workarea.height - target_height) // 2)
                self.move(x, y)
                self._saved_x = x
                self._saved_y = y

            self._saved_width = target_width
            self._saved_height = target_height
            if self._is_maximized:
                self.maximize()
        except Exception:
            pass

        return False

    def _load_window_geometry(self) -> None:
        """Load window geometry from persisted config."""
        raw = getattr(self._context.config, "window_size", "")
        if not raw:
            return

        parts = [part.strip() for part in raw.split(",")]
        if len(parts) < 4:
            return

        try:
            width = int(parts[0])
            height = int(parts[1])
            x = int(parts[2])
            y = int(parts[3])
            maximized = bool(int(parts[4])) if len(parts) > 4 else False
        except Exception:
            return

        if width > 0:
            self._saved_width = width
        if height > 0:
            self._saved_height = height
        if x >= 0 and y >= 0:
            self._saved_x = x
            self._saved_y = y
        self._is_maximized = maximized

    def _save_window_geometry(self) -> None:
        """Persist current window geometry to config."""
        if self._saved_x is None:
            self._saved_x = 0
        if self._saved_y is None:
            self._saved_y = 0

        self._context.config.window_size = (
            f"{self._saved_width},{self._saved_height},{self._saved_x},"
            f"{self._saved_y},{1 if self._is_maximized else 0}"
        )

    def _on_window_state_event(self, widget: Gtk.Widget, event: Gdk.EventWindowState) -> None:
        """Handle window state changes (maximize/restore)."""
        is_maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)

        if self._is_maximized and not is_maximized:
            self.resize(self._saved_width, self._saved_height)

        self._is_maximized = is_maximized
        self._save_window_geometry()

    def _on_configure_event(self, widget: Gtk.Widget, event: Gdk.EventConfigure) -> None:
        """Handle window configuration changes (size/position)."""
        if not self._is_maximized:
            width, height = self.get_size()
            if width > 0 and height > 0:
                self._saved_width = width
                self._saved_height = height
            if event.x >= 0 and event.y >= 0:
                self._saved_x = event.x
                self._saved_y = event.y
        self._save_window_geometry()
        return False

    def _on_delete(self, widget: Gtk.Widget, event: Gdk.Event) -> bool:
        """Handle window close - hide instead of closing."""
        self._save_window_geometry()
        self._context.save_config()
        self.hide()
        return True

    def _on_destroy(self, widget: Gtk.Widget) -> None:
        """Handle window destruction - cleanup resources."""
        self._save_window_geometry()
        self._context.save_config()
        # Remove state listener to prevent memory leak
        try:
            self._context.proxy_state.remove_listener(self._on_state_changed)
        except Exception:
            pass

    def show_all(self) -> None:
        """Override show_all."""
        super().show_all()

    def set_on_connect(self, callback: Callable[[int], None]) -> None:
        """Set callback for connection."""
        self._on_connect = callback

    def set_on_disconnect(self, callback: Callable[[], None]) -> None:
        """Set callback for disconnection."""
        self._on_disconnect = callback

    def set_on_config_reload(self, callback: Callable[[], None]) -> None:
        """Set callback for configuration reload."""
        self._on_config_reload = callback

    def set_on_test_latency(self, callback: Callable[[int], int] | None) -> None:
        """Set callback for profile latency test."""
        self._on_test_latency = callback

    def refresh(self) -> None:
        """Refresh UI."""
        GLib.idle_add(self._refresh_profiles)
        GLib.idle_add(self._refresh_subscriptions)
        self._update_monitoring_tab_visibility()

    def _update_monitoring_tab_visibility(self) -> None:
        """Update monitoring tab visibility based on settings."""
        if not self._monitoring_notebook or not self._monitoring_page:
            return

        monitoring_enabled = self._context.config.monitoring.enabled

        # Find monitoring page index
        num_pages = self._monitoring_notebook.get_n_pages()
        monitoring_index = -1
        for i in range(num_pages):
            if self._monitoring_notebook.get_nth_page(i) == self._monitoring_page:
                monitoring_index = i
                break

        if monitoring_enabled:
            if monitoring_index < 0:
                self._monitoring_page_index = self._monitoring_notebook.insert_page(
                    self._monitoring_page, Gtk.Label(label="Мониторинг"), 2
                )
                self._monitoring_notebook.show_all()
        else:
            if monitoring_index >= 0:
                self._monitoring_notebook.remove_page(monitoring_index)
                self._monitoring_page_index = -1

    def update_monitoring_status(
        self,
        proxy_ok: bool,
        vpn_ok: bool,
        last_check_time: float,
        proxy_error: str = "",
        vpn_error: str = "",
    ) -> None:
        """Update monitoring status display."""
        if not self._monitoring_proxy_status or not self._monitoring_vpn_status:
            return

        # Update proxy status
        ctx = self._monitoring_proxy_status.get_style_context()
        ctx.remove_class("status-connected")
        ctx.remove_class("status-disconnected")

        if proxy_ok:
            self._monitoring_proxy_status.set_text("🟢 Работает")
            ctx.add_class("status-connected")
        else:
            self._monitoring_proxy_status.set_text("🔴 Не работает")
            if proxy_error:
                self._monitoring_proxy_status.set_tooltip_text(proxy_error)
            ctx.add_class("status-disconnected")

        # Update VPN status
        ctx = self._monitoring_vpn_status.get_style_context()
        ctx.remove_class("status-connected")
        ctx.remove_class("status-disconnected")

        if vpn_ok:
            self._monitoring_vpn_status.set_text("🟢 Подключен")
            ctx.add_class("status-connected")
        else:
            self._monitoring_vpn_status.set_text("🔴 Отключен")
            if vpn_error:
                self._monitoring_vpn_status.set_tooltip_text(vpn_error)
            ctx.add_class("status-disconnected")

        # Update last check time
        if self._monitoring_last_check:
            if last_check_time > 0:
                import datetime

                check_time = datetime.datetime.fromtimestamp(last_check_time)
                time_str = check_time.strftime("%H:%M:%S")
                self._monitoring_last_check.set_text(time_str)
            else:
                self._monitoring_last_check.set_text("—")
