from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import gi

gi.require_version('Gtk', '3.0')

try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
except ValueError:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3

from gi.repository import Gtk, GLib

if TYPE_CHECKING:
    from src.core.context import AppContext, ProxyState
    from src.db.profiles import ProfileEntry


class TrayIcon:
    """System tray icon."""
    
    APP_ID = "tenga-proxy"
    ICON_DISCONNECTED = "tenga-proxy"
    ICON_CONNECTED = "tenga-proxy"
    ICON_CONNECTING = "tenga-proxy"
    
    def __init__(self, context: 'AppContext'):
        self._context = context
        self._indicator: Optional[AppIndicator3.Indicator] = None
        self._menu: Optional[Gtk.Menu] = None
        
        # Callbacks
        self._on_connect: Optional[Callable[[], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._on_select_profile: Optional[Callable[[int], None]] = None
        self._on_add_profile: Optional[Callable[[], None]] = None
        self._on_show_window: Optional[Callable[[], None]] = None
        self._on_settings: Optional[Callable[[], None]] = None
        self._on_quit: Optional[Callable[[], None]] = None
        # Menu items for updates
        self._connect_item: Optional[Gtk.MenuItem] = None
        self._status_item: Optional[Gtk.MenuItem] = None
        self._profiles_menu: Optional[Gtk.Menu] = None
        
        self._setup_indicator()
        
        # Subscribe to state changes
        self._context.proxy_state.add_listener(self._on_state_changed)
    
    def _setup_indicator(self) -> None:
        """Setup indicator."""
        self._indicator = AppIndicator3.Indicator.new(
            self.APP_ID,
            self.ICON_DISCONNECTED,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._indicator.set_title("Tenga Proxy")
        
        self._build_menu()
        self._indicator.set_menu(self._menu)
    
    def _build_menu(self) -> None:
        """Build menu."""
        self._menu = Gtk.Menu()
        
        # Status
        self._status_item = Gtk.MenuItem(label="Статус: Отключено")
        self._status_item.set_sensitive(False)
        self._menu.append(self._status_item)
        
        self._menu.append(Gtk.SeparatorMenuItem())
        # Connect/Disconnect
        self._connect_item = Gtk.MenuItem(label="Подключить")
        self._connect_item.connect("activate", self._on_connect_clicked)
        self._menu.append(self._connect_item)
        
        self._menu.append(Gtk.SeparatorMenuItem())
        # Profiles
        profiles_item = Gtk.MenuItem(label="Профили")
        self._profiles_menu = Gtk.Menu()
        profiles_item.set_submenu(self._profiles_menu)
        self._menu.append(profiles_item)
        
        self._update_profiles_menu()
        # Add profile
        add_profile_item = Gtk.MenuItem(label="Добавить профиль...")
        add_profile_item.connect("activate", self._on_add_profile_clicked)
        self._menu.append(add_profile_item)
        
        self._menu.append(Gtk.SeparatorMenuItem())
        # Show window
        show_item = Gtk.MenuItem(label="Открыть окно")
        show_item.connect("activate", self._on_show_clicked)
        self._menu.append(show_item)
        # Settings
        settings_item = Gtk.MenuItem(label="Настройки...")
        settings_item.connect("activate", self._on_settings_clicked)
        self._menu.append(settings_item)
        
        self._menu.append(Gtk.SeparatorMenuItem())
        # Quit
        quit_item = Gtk.MenuItem(label="Выход")
        quit_item.connect("activate", self._on_quit_clicked)
        self._menu.append(quit_item)
        
        self._menu.show_all()
    
    def _update_profiles_menu(self) -> None:
        """Update profiles menu."""
        if not self._profiles_menu:
            return
        
        # Clear menu
        for child in self._profiles_menu.get_children():
            self._profiles_menu.remove(child)
        # Get profiles of current group
        profiles = self._context.profiles.get_current_group_profiles()
        
        if not profiles:
            no_profiles = Gtk.MenuItem(label="(нет профилей)")
            no_profiles.set_sensitive(False)
            self._profiles_menu.append(no_profiles)
        else:
            current_id = self._context.proxy_state.started_profile_id
            
            for profile in profiles:
                label = profile.name
                if profile.id == current_id:
                    label = f"✓ {label}"
                
                item = Gtk.MenuItem(label=label)
                item.connect("activate", self._on_profile_clicked, profile.id)
                self._profiles_menu.append(item)
        
        self._profiles_menu.show_all()
    
    def _on_state_changed(self, state: 'ProxyState') -> None:
        """State change handler."""
        GLib.idle_add(self._update_ui, state)
    
    def _update_ui(self, state: 'ProxyState') -> None:
        """Update UI in main thread."""
        if state.is_running:
            self._indicator.set_icon_full(self.ICON_CONNECTED, "Connected")
            self._status_item.set_label("Статус: Подключено")
            self._connect_item.set_label("Отключить")

            # Show profile name
            profile = self._context.profiles.get_profile(state.started_profile_id)
            if profile:
                self._status_item.set_label(f"Статус: {profile.name}")
        else:
            self._indicator.set_icon_full(self.ICON_DISCONNECTED, "Disconnected")
            self._status_item.set_label("Статус: Отключено")
            self._connect_item.set_label("Подключить")
        
        self._update_profiles_menu()
    
    def _on_connect_clicked(self, widget: Gtk.MenuItem) -> None:
        """Click on Connect/Disconnect."""
        if self._context.proxy_state.is_running:
            if self._on_disconnect:
                self._on_disconnect()
        else:
            if self._on_connect:
                self._on_connect()
    
    def _on_profile_clicked(self, widget: Gtk.MenuItem, profile_id: int) -> None:
        """Click on profile."""
        if self._on_select_profile:
            self._on_select_profile(profile_id)
    
    def _on_add_profile_clicked(self, widget: Gtk.MenuItem) -> None:
        """Click on Add profile."""
        if self._on_add_profile:
            self._on_add_profile()
    
    def _on_show_clicked(self, widget: Gtk.MenuItem) -> None:
        """Click on Open."""
        if self._on_show_window:
            self._on_show_window()
    
    def _on_settings_clicked(self, widget: Gtk.MenuItem) -> None:
        """Click on Settings."""
        if self._on_settings:
            self._on_settings()
    
    def _on_quit_clicked(self, widget: Gtk.MenuItem) -> None:
        """Click on Quit."""
        if self._on_quit:
            self._on_quit()
        else:
            Gtk.main_quit()
    
    def set_on_connect(self, callback: Callable[[], None]) -> None:
        """Set callback for connection."""
        self._on_connect = callback
    
    def set_on_disconnect(self, callback: Callable[[], None]) -> None:
        """Set callback for disconnection."""
        self._on_disconnect = callback
    
    def set_on_select_profile(self, callback: Callable[[int], None]) -> None:
        """Set callback for profile selection."""
        self._on_select_profile = callback
    
    def set_on_add_profile(self, callback: Callable[[], None]) -> None:
        """Set callback for adding profile."""
        self._on_add_profile = callback
    
    def set_on_show_window(self, callback: Callable[[], None]) -> None:
        """Set callback for opening window."""
        self._on_show_window = callback
    
    def set_on_settings(self, callback: Callable[[], None]) -> None:
        """Set callback for settings."""
        self._on_settings = callback
    
    def set_on_quit(self, callback: Callable[[], None]) -> None:
        """Set callback for quit."""
        self._on_quit = callback
    
    def refresh_profiles(self) -> None:
        """Refresh profile list."""
        GLib.idle_add(self._update_profiles_menu)
    
    def show_notification(self, title: str, message: str) -> None:
        """Show notification."""
        try:
            gi.require_version('Notify', '0.7')
            from gi.repository import Notify
            
            if not Notify.is_initted():
                Notify.init("Tenga")
            
            notification = Notify.Notification.new(title, message, self.ICON_CONNECTED)
            notification.show()
        except Exception as e:
            print(f"Failed to show notification: {e}")
    
    def cleanup(self) -> None:
        """Cleanup resources - remove listeners."""
        try:
            self._context.proxy_state.remove_listener(self._on_state_changed)
        except Exception:
            pass