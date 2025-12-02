from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable, Optional

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gdk, GLib, Pango
from src.ui.dialogs import show_edit_profile_dialog

if TYPE_CHECKING:
    from src.core.context import AppContext, ProxyState
    from src.db.profiles import ProfileEntry


def format_bytes(bytes_count: int) -> str:
    """Format bytes to human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


class MainWindow(Gtk.Window):
    """Main application window."""
    
    def __init__(self, context: 'AppContext'):
        super().__init__(title="Tenga Proxy")
        
        self._context = context
        
        # Callbacks
        self._on_connect: Optional[Callable[[int], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        # UI elements
        self._profile_list: Optional[Gtk.TreeView] = None
        self._profile_store: Optional[Gtk.ListStore] = None
        self._connect_button: Optional[Gtk.Button] = None
        self._status_label: Optional[Gtk.Label] = None
        # Stats UI elements
        self._stats_frame: Optional[Gtk.Frame] = None
        self._upload_label: Optional[Gtk.Label] = None
        self._download_label: Optional[Gtk.Label] = None
        self._connections_label: Optional[Gtk.Label] = None
        self._version_label: Optional[Gtk.Label] = None
        self._delay_label: Optional[Gtk.Label] = None
        # Stats update timer
        self._stats_timer_id: Optional[int] = None
        
        self._setup_window()
        self._setup_ui()
        
        # Subscribe to state changes
        self._context.proxy_state.add_listener(self._on_state_changed)
        # Initial update
        self._refresh_profiles()
        self._update_ui(self._context.proxy_state)
    
    def _setup_window(self) -> None:
        """Setup window."""
        self.set_default_size(400, 500)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(10)
        self.set_icon_name("network-transmit-receive")
        # Icon from file file:
        # icon_path = Path(__file__).parent.parent.parent / "res" / "icon.png"
        # if icon_path.exists():
        #     self.set_icon_from_file(str(icon_path))
        
        # On close - hide
        self.connect("delete-event", self._on_delete)

        css = b"""
        .status-connected {
            color: #4CAF50;
            font-weight: bold;
        }
        .status-disconnected {
            color: #9E9E9E;
        }
        .connect-button {
            padding: 10px 20px;
        }
        .stats-frame {
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 8px;
        }
        .stats-label {
            font-family: monospace;
            font-size: 11px;
        }
        .stats-value {
            font-weight: bold;
            color: #2196F3;
        }
        .stats-upload {
            color: #FF5722;
        }
        .stats-download {
            color: #4CAF50;
        }
        .delay-good {
            color: #4CAF50;
        }
        .delay-medium {
            color: #FF9800;
        }
        .delay-bad {
            color: #F44336;
        }
        """
        
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_box)
        
        # Header
        header = Gtk.Label()
        header.set_markup("<big><b>Tenga Proxy</b></big>")
        main_box.pack_start(header, False, False, 5)
        # Status
        self._status_label = Gtk.Label(label="Статус: Отключено")
        self._status_label.get_style_context().add_class("status-disconnected")
        main_box.pack_start(self._status_label, False, False, 5)
        # Statistics panel
        self._setup_stats_panel(main_box)
        # Separator
        main_box.pack_start(Gtk.Separator(), False, False, 5)
        # Profile list
        profiles_label = Gtk.Label()
        profiles_label.set_markup("<b>Профили</b>")
        profiles_label.set_halign(Gtk.Align.START)
        main_box.pack_start(profiles_label, False, False, 0)
        # ScrolledWindow for list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        main_box.pack_start(scrolled, True, True, 0)
        # TreeView
        self._profile_store = Gtk.ListStore(int, str, str, str)  # id, name, type, address
        self._profile_list = Gtk.TreeView(model=self._profile_store)
        self._profile_list.set_headers_visible(True)
        # Columns
        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        
        col_name = Gtk.TreeViewColumn("Имя", renderer, text=1)
        col_name.set_expand(True)
        col_name.set_min_width(150)
        self._profile_list.append_column(col_name)
        
        col_type = Gtk.TreeViewColumn("Тип", renderer, text=2)
        col_type.set_min_width(70)
        self._profile_list.append_column(col_type)
        
        col_addr = Gtk.TreeViewColumn("Сервер", renderer, text=3)
        col_addr.set_min_width(100)
        self._profile_list.append_column(col_addr)
        
        # Selection on double click
        self._profile_list.connect("row-activated", self._on_row_activated)
        
        scrolled.add(self._profile_list)
        # Profile management buttons
        profile_button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        profile_button_box.set_halign(Gtk.Align.START)
        main_box.pack_start(profile_button_box, False, False, 0)
        
        add_button = Gtk.Button(label="[+] Добавить")
        add_button.set_tooltip_text("Добавить профиль по share link")
        add_button.connect("clicked", self._on_add_clicked)
        profile_button_box.pack_start(add_button, False, False, 0)

        edit_button = Gtk.Button(label="[Edit] Редактировать")
        edit_button.set_tooltip_text("Редактировать выбранный профиль")
        edit_button.connect("clicked", self._on_edit_profile_clicked)
        profile_button_box.pack_start(edit_button, False, False, 0)

        delete_button = Gtk.Button(label="[Del] Удалить")
        delete_button.set_tooltip_text("Удалить выбранный профиль")
        delete_button.connect("clicked", self._on_delete_profile_clicked)
        profile_button_box.pack_start(delete_button, False, False, 0)
        
        # Separator
        main_box.pack_start(Gtk.Separator(), False, False, 5)
        # Connection buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(button_box, False, False, 10)
        
        self._connect_button = Gtk.Button(label="Подключить")
        self._connect_button.get_style_context().add_class("connect-button")
        self._connect_button.connect("clicked", self._on_connect_clicked)
        button_box.pack_start(self._connect_button, False, False, 0)
        
        refresh_button = Gtk.Button(label="Обновить")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        button_box.pack_start(refresh_button, False, False, 0)
        
        settings_button = Gtk.Button(label="[Settings] Настройки")
        settings_button.set_tooltip_text("Настройки приложения")
        settings_button.connect("clicked", self._on_settings_clicked)
        button_box.pack_start(settings_button, False, False, 0)
    
    def _setup_stats_panel(self, parent_box: Gtk.Box) -> None:
        """Setup statistics panel."""
        expander = Gtk.Expander(label="📊 Статистика")
        expander.set_expanded(False)
        parent_box.pack_start(expander, False, False, 5)
        
        # Stats frame
        self._stats_frame = Gtk.Frame()
        self._stats_frame.get_style_context().add_class("stats-frame")
        expander.add(self._stats_frame)
        
        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        stats_box.set_margin_top(8)
        stats_box.set_margin_bottom(8)
        stats_box.set_margin_start(8)
        stats_box.set_margin_end(8)
        self._stats_frame.add(stats_box)

        stats_grid = Gtk.Grid()
        stats_grid.set_column_spacing(15)
        stats_grid.set_row_spacing(5)
        stats_box.pack_start(stats_grid, False, False, 0)
        
        # Version
        version_title = Gtk.Label(label="Версия sing-box:")
        version_title.set_halign(Gtk.Align.START)
        version_title.get_style_context().add_class("stats-label")
        stats_grid.attach(version_title, 0, 0, 1, 1)
        
        self._version_label = Gtk.Label(label="—")
        self._version_label.set_halign(Gtk.Align.START)
        self._version_label.get_style_context().add_class("stats-value")
        stats_grid.attach(self._version_label, 1, 0, 1, 1)
        # Upload
        upload_title = Gtk.Label(label="↑ Отправлено:")
        upload_title.set_halign(Gtk.Align.START)
        upload_title.get_style_context().add_class("stats-label")
        stats_grid.attach(upload_title, 0, 1, 1, 1)
        
        self._upload_label = Gtk.Label(label="0 B")
        self._upload_label.set_halign(Gtk.Align.START)
        self._upload_label.get_style_context().add_class("stats-upload")
        stats_grid.attach(self._upload_label, 1, 1, 1, 1)
        # Download
        download_title = Gtk.Label(label="↓ Получено:")
        download_title.set_halign(Gtk.Align.START)
        download_title.get_style_context().add_class("stats-label")
        stats_grid.attach(download_title, 0, 2, 1, 1)
        
        self._download_label = Gtk.Label(label="0 B")
        self._download_label.set_halign(Gtk.Align.START)
        self._download_label.get_style_context().add_class("stats-download")
        stats_grid.attach(self._download_label, 1, 2, 1, 1)
        # Connections count
        conn_title = Gtk.Label(label="Подключений:")
        conn_title.set_halign(Gtk.Align.START)
        conn_title.get_style_context().add_class("stats-label")
        stats_grid.attach(conn_title, 0, 3, 1, 1)
        
        self._connections_label = Gtk.Label(label="0")
        self._connections_label.set_halign(Gtk.Align.START)
        self._connections_label.get_style_context().add_class("stats-value")
        stats_grid.attach(self._connections_label, 1, 3, 1, 1)
        # Delay
        delay_title = Gtk.Label(label="Задержка:")
        delay_title.set_halign(Gtk.Align.START)
        delay_title.get_style_context().add_class("stats-label")
        stats_grid.attach(delay_title, 0, 4, 1, 1)
        
        self._delay_label = Gtk.Label(label="—")
        self._delay_label.set_halign(Gtk.Align.START)
        stats_grid.attach(self._delay_label, 1, 4, 1, 1)
        # Buttons row
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        button_box.set_margin_top(10)
        stats_box.pack_start(button_box, False, False, 0)
        # Test delay button
        test_delay_btn = Gtk.Button(label="🔍 Тест задержки")
        test_delay_btn.set_tooltip_text("Проверить задержку до прокси-сервера")
        test_delay_btn.connect("clicked", self._on_test_delay_clicked)
        button_box.pack_start(test_delay_btn, False, False, 0)
        # View connections button
        view_conn_btn = Gtk.Button(label="📋 Подключения")
        view_conn_btn.set_tooltip_text("Показать активные подключения")
        view_conn_btn.connect("clicked", self._on_view_connections_clicked)
        button_box.pack_start(view_conn_btn, False, False, 0)
        # Close all connections button
        close_all_btn = Gtk.Button(label="❌ Закрыть все")
        close_all_btn.set_tooltip_text("Закрыть все активные подключения")
        close_all_btn.connect("clicked", self._on_close_all_connections_clicked)
        button_box.pack_start(close_all_btn, False, False, 0)
    
    def _start_stats_timer(self) -> None:
        """Start statistics update timer."""
        if self._stats_timer_id is not None:
            return
        
        # Update stats
        self._stats_timer_id = GLib.timeout_add(2000, self._update_stats)

        self._update_stats()
        self._update_version()
    
    def _stop_stats_timer(self) -> None:
        """Stop statistics update timer."""
        if self._stats_timer_id is not None:
            GLib.source_remove(self._stats_timer_id)
            self._stats_timer_id = None
    
    def _update_stats(self) -> bool:
        """Update statistics from Clash API. Returns True to continue timer."""
        if not self._context.proxy_state.is_running:
            return False  # Stop timer
        
        try:
            manager = self._context.singbox_manager
            
            # Get traffic stats
            traffic = manager.get_traffic()
            self._upload_label.set_text(format_bytes(traffic.upload))
            self._download_label.set_text(format_bytes(traffic.download))
            # Update proxy state with traffic
            self._context.proxy_state.upload_bytes = traffic.upload
            self._context.proxy_state.download_bytes = traffic.download
            # Get connections count
            connections = manager.get_connections()
            self._connections_label.set_text(str(len(connections)))
            
        except Exception as e:
            pass
        
        return True
    
    def _update_version(self) -> None:
        """Update sing-box version."""
        if not self._context.proxy_state.is_running:
            self._version_label.set_text("—")
            return
        
        try:
            manager = self._context.singbox_manager
            version_info = manager.get_version()
            if version_info:
                version = version_info.get("version", "?")
                self._version_label.set_text(version)
            else:
                self._version_label.set_text("—")
        except Exception:
            self._version_label.set_text("—")
    
    def _reset_stats_display(self) -> None:
        """Reset stats display to default values."""
        self._upload_label.set_text("0 B")
        self._download_label.set_text("0 B")
        self._connections_label.set_text("0")
        self._delay_label.set_text("—")
        self._version_label.set_text("—")

        ctx = self._delay_label.get_style_context()
        ctx.remove_class("delay-good")
        ctx.remove_class("delay-medium")
        ctx.remove_class("delay-bad")
    
    def _on_test_delay_clicked(self, button: Gtk.Button) -> None:
        """Test proxy delay."""
        if not self._context.proxy_state.is_running:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Прокси не подключен",
            )
            dialog.format_secondary_text("Подключитесь к прокси для тестирования задержки.")
            dialog.run()
            dialog.destroy()
            return
        
        # Show testing status
        self._delay_label.set_text("...")
        # Run test in background
        def do_test():
            try:
                manager = self._context.singbox_manager
                delay = manager.test_delay("proxy")
                GLib.idle_add(self._show_delay_result, delay)
            except Exception as e:
                GLib.idle_add(self._show_delay_result, -1)

        thread = threading.Thread(target=do_test, daemon=True)
        thread.start()
    
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
    
    def _on_view_connections_clicked(self, button: Gtk.Button) -> None:
        """Show connections dialog."""
        if not self._context.proxy_state.is_running:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Прокси не подключен",
            )
            dialog.format_secondary_text("Подключитесь к прокси для просмотра подключений.")
            dialog.run()
            dialog.destroy()
            return
        
        self._show_connections_dialog()
    
    def _show_connections_dialog(self) -> None:
        """Show connections in a dialog."""
        manager = self._context.singbox_manager
        connections = manager.get_connections()
        
        dialog = Gtk.Dialog(
            title="Активные подключения",
            transient_for=self,
            flags=0,
        )
        dialog.add_button("Закрыть", Gtk.ResponseType.CLOSE)
        dialog.add_button("Обновить", Gtk.ResponseType.APPLY)
        dialog.set_default_size(700, 400)
        
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(10)
        content.set_margin_end(10)
        
        # Header
        header_label = Gtk.Label()
        header_label.set_markup(f"<b>Всего подключений: {len(connections)}</b>")
        header_label.set_halign(Gtk.Align.START)
        content.pack_start(header_label, False, False, 0)
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scrolled, True, True, 0)
        # TreeView for connections
        # Columns: host, network, download, upload, chain, rule
        store = Gtk.ListStore(str, str, str, str, str, str, str)  # +id for closing
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        
        renderer = Gtk.CellRendererText()
        renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        
        columns = [
            ("Хост", 200),
            ("Сеть", 60),
            ("Получено", 80),
            ("Отправлено", 80),
            ("Цепочка", 100),
            ("Правило", 100),
        ]
        
        for i, (title, width) in enumerate(columns):
            col = Gtk.TreeViewColumn(title, renderer, text=i)
            col.set_min_width(width)
            col.set_resizable(True)
            tree.append_column(col)

        for conn in connections:
            metadata = conn.metadata
            host = metadata.get("destinationAddress", "") or metadata.get("host", "")
            network = metadata.get("network", "tcp")
            download = format_bytes(conn.download)
            upload = format_bytes(conn.upload)
            chain = " → ".join(conn.chains) if conn.chains else "—"
            rule = conn.rule or "—"
            
            store.append([host, network, download, upload, chain, rule, conn.id])
        
        scrolled.add(tree)
        
        # Close connection button
        close_btn = Gtk.Button(label="Закрыть выбранное подключение")
        close_btn.connect("clicked", self._on_close_connection_clicked, tree, store, header_label)
        content.pack_start(close_btn, False, False, 0)
        
        dialog.show_all()
        
        while True:
            response = dialog.run()
            if response == Gtk.ResponseType.APPLY:
                store.clear()
                connections = manager.get_connections()
                header_label.set_markup(f"<b>Всего подключений: {len(connections)}</b>")
                for conn in connections:
                    metadata = conn.metadata
                    host = metadata.get("destinationAddress", "") or metadata.get("host", "")
                    network = metadata.get("network", "tcp")
                    download = format_bytes(conn.download)
                    upload = format_bytes(conn.upload)
                    chain = " → ".join(conn.chains) if conn.chains else "—"
                    rule = conn.rule or "—"
                    store.append([host, network, download, upload, chain, rule, conn.id])
            else:
                break
        
        dialog.destroy()
    
    def _on_close_connection_clicked(
        self,
        button: Gtk.Button,
        tree: Gtk.TreeView,
        store: Gtk.ListStore,
        header_label: Gtk.Label,
    ) -> None:
        """Close selected connection."""
        selection = tree.get_selection()
        model, treeiter = selection.get_selected()
        
        if not treeiter:
            return
        
        conn_id = model[treeiter][6]
        
        manager = self._context.singbox_manager
        if manager.close_connection(conn_id):
            store.remove(treeiter)
            # Update header
            count = len(store)
            header_label.set_markup(f"<b>Всего подключений: {count}</b>")
    
    def _on_close_all_connections_clicked(self, button: Gtk.Button) -> None:
        """Close all connections."""
        if not self._context.proxy_state.is_running:
            return
        
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Закрыть все подключения?",
        )
        dialog.format_secondary_text("Все активные подключения будут разорваны.")
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            manager = self._context.singbox_manager
            if manager.close_all_connections():
                self._connections_label.set_text("0")

    def _refresh_profiles(self) -> None:
        """Refresh profile list."""
        self._profile_store.clear()
        
        profiles = self._context.profiles.get_current_group_profiles()
        current_id = self._context.proxy_state.started_profile_id
        
        for profile in profiles:
            name = profile.name
            if profile.id == current_id:
                name = f"[*] {name}"
            
            self._profile_store.append([
                profile.id,
                name,
                profile.proxy_type.upper(),
                profile.bean.display_address,
            ])
    
    def _on_state_changed(self, state: 'ProxyState') -> None:
        """State change handler."""
        GLib.idle_add(self._update_ui, state)
    
    def _update_ui(self, state: 'ProxyState') -> None:
        """Update UI."""
        if state.is_running:
            profile = self._context.profiles.get_profile(state.started_profile_id)
            name = profile.name if profile else "Unknown"
            
            self._status_label.set_text(f"Статус: Подключено ({name})")
            self._status_label.get_style_context().remove_class("status-disconnected")
            self._status_label.get_style_context().add_class("status-connected")
            
            self._connect_button.set_label("Отключить")
            self._start_stats_timer()
        else:
            self._status_label.set_text("Статус: Отключено")
            self._status_label.get_style_context().remove_class("status-connected")
            self._status_label.get_style_context().add_class("status-disconnected")
            
            self._connect_button.set_label("Подключить")
            self._stop_stats_timer()
            self._reset_stats_display()
        
        self._refresh_profiles()
    
    def _get_selected_profile_id(self) -> Optional[int]:
        """Get selected profile ID."""
        selection = self._profile_list.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            return model[treeiter][0]
        return None
    
    def _on_row_activated(self, tree_view: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn) -> None:
        """Double click on profile."""
        model = tree_view.get_model()
        treeiter = model.get_iter(path)
        profile_id = model[treeiter][0]

        if self._on_connect:
            self._on_connect(profile_id)
    
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
                # Show selection dialog
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Выберите профиль",
                )
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
            dialog.format_secondary_text(f"{entry.name}\n{profile.display_address}")
            dialog.run()
            dialog.destroy()
    
    def _on_delete_profile_clicked(self, button: Gtk.Button) -> None:
        """Click on Delete button."""
        profile_id = self._get_selected_profile_id()
        
        if profile_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите профиль",
            )
            dialog.format_secondary_text("Выберите профиль для удаления.")
            dialog.run()
            dialog.destroy()
            return
        
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
        dialog.format_secondary_text(f"Удалить профиль '{profile.name}'?")
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            self._context.profiles.remove_profile(profile_id)
            self._context.profiles.save()
            self._refresh_profiles()

    def _on_edit_profile_clicked(self, button: Gtk.Button) -> None:
        """Click on Edit button."""
        profile_id = self._get_selected_profile_id()

        if profile_id is None:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Выберите профиль",
            )
            dialog.format_secondary_text("Выберите профиль для редактирования.")
            dialog.run()
            dialog.destroy()
            return

        profile = self._context.profiles.get_profile(profile_id)
        if not profile:
            return

        changed = show_edit_profile_dialog(profile, self)
        if changed:
            self._context.profiles.save()
            self._refresh_profiles()
    
    def _on_settings_clicked(self, button: Gtk.Button) -> None:
        """Click on Settings button."""
        from src.ui.dialogs import show_settings_dialog
        show_settings_dialog(self._context, self)
    
    def _on_delete(self, widget: Gtk.Widget, event: Gdk.Event) -> bool:
        """Handle window close - hide instead of closing."""
        # Stop stats timer when window is hidden
        self._stop_stats_timer()
        self.hide()
        return True
    
    def show_all(self) -> None:
        """Override show_all to restart stats timer if connected."""
        super().show_all()
        if self._context.proxy_state.is_running:
            self._start_stats_timer()

    
    def set_on_connect(self, callback: Callable[[int], None]) -> None:
        """Set callback for connection."""
        self._on_connect = callback
    
    def set_on_disconnect(self, callback: Callable[[], None]) -> None:
        """Set callback for disconnection."""
        self._on_disconnect = callback
    
    def refresh(self) -> None:
        """Refresh UI."""
        GLib.idle_add(self._refresh_profiles)
