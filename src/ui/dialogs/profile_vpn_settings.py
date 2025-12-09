from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Callable

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gdk, Pango

from src.db.config import VpnSettings, RoutingSettings
from src.sys.vpn import is_vpn_active, get_vpn_interface, list_vpn_connections, list_network_interfaces

if TYPE_CHECKING:
    from src.db.profiles import ProfileEntry

logger = logging.getLogger("tenga.ui.profile_vpn_settings")


class ProfileVpnSettingsDialog(Gtk.Dialog):
    """VPN settings dialog for a specific profile."""
    
    def __init__(self, profile: 'ProfileEntry', parent: Optional[Gtk.Window] = None):
        super().__init__(
            title=f"Настройки VPN - {profile.name}",
            transient_for=parent,
            flags=0,
        )
        self.set_wmclass("tenga-proxy", "tenga-proxy")
        self.set_role("tenga-proxy")
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.connect("realize", self._on_realize)
        
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_APPLY, Gtk.ResponseType.APPLY,
        )
        
        self.set_default_size(650, 600)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)
        
        self._profile = profile
        self._routing = RoutingSettings()
        
        self._setup_ui()
        self._load_settings()
    
    def _on_realize(self, widget: Gtk.Widget) -> None:
        """Handle window realization - set WM_CLASS via Gdk.Window."""
        window = self.get_window()
        if window:
            try:
                window.set_wmclass("tenga-proxy", "tenga-proxy")
                self.set_skip_taskbar_hint(True)
            except Exception:
                pass
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        content = self.get_content_area()
        content.set_spacing(0)
        
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scrolled, True, True, 0)
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)

        enable_frame = Gtk.Frame()
        enable_frame.set_label("Интеграция VPN")
        box.pack_start(enable_frame, False, False, 0)
        
        enable_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        enable_box.set_margin_start(10)
        enable_box.set_margin_end(10)
        enable_box.set_margin_top(10)
        enable_box.set_margin_bottom(10)
        enable_frame.add(enable_box)
        
        self._vpn_enable_check = Gtk.CheckButton(label="Включить интеграцию VPN")
        self._vpn_enable_check.set_tooltip_text(
            "Автоматически маршрутизировать часть трафика через VPN.\n"
            "VPN должен быть подключен вручную через NetworkManager."
        )
        self._vpn_enable_check.connect("toggled", self._on_vpn_enable_changed)
        enable_box.pack_start(self._vpn_enable_check, False, False, 0)

        connection_frame = Gtk.Frame()
        connection_frame.set_label("Подключение VPN")
        box.pack_start(connection_frame, False, False, 0)
        
        connection_grid = Gtk.Grid()
        connection_grid.set_row_spacing(8)
        connection_grid.set_column_spacing(10)
        connection_grid.set_margin_start(10)
        connection_grid.set_margin_end(10)
        connection_grid.set_margin_top(10)
        connection_grid.set_margin_bottom(10)
        connection_frame.add(connection_grid)
        
        connection_grid.attach(Gtk.Label(label="Имя подключения:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._vpn_connection_entry = Gtk.Entry()
        self._vpn_connection_entry.set_placeholder_text("aiso")
        self._vpn_connection_entry.set_tooltip_text("Имя VPN подключения в NetworkManager")
        connection_grid.attach(self._vpn_connection_entry, 1, 0, 1, 1)

        try:
            vpn_names = list_vpn_connections()
        except Exception:
            vpn_names = []

        if vpn_names:
            store = Gtk.ListStore(str)
            for name in vpn_names:
                store.append([name])
            completion = Gtk.EntryCompletion()
            completion.set_model(store)
            completion.set_text_column(0)
            completion.set_inline_completion(True)
            completion.set_inline_selection(True)
            self._vpn_connection_entry.set_completion(completion)
        
        connection_grid.attach(Gtk.Label(label="Интерфейс VPN:", halign=Gtk.Align.END), 0, 1, 1, 1)
        self._vpn_interface_combo = Gtk.ComboBoxText()
        self._vpn_interface_combo.set_tooltip_text("Выберите интерфейс VPN. 'Автоопределение' - автоматический выбор.")
        self._vpn_interface_combo.append_text("Автоопределение")
        self._vpn_interface_combo.set_active(0)
        try:
            interfaces = list_network_interfaces()
            for iface in interfaces:
                self._vpn_interface_combo.append_text(iface)
        except Exception:
            pass
        connection_grid.attach(self._vpn_interface_combo, 1, 1, 1, 1)

        connection_grid.attach(Gtk.Label(label="Интерфейс Direct:", halign=Gtk.Align.END), 0, 2, 1, 1)
        self._direct_interface_combo = Gtk.ComboBoxText()
        self._direct_interface_combo.set_tooltip_text("Выберите интерфейс для прямого трафика (обход VPN). 'Автоопределение' - автоматический выбор.")
        self._direct_interface_combo.append_text("Автоопределение")
        self._direct_interface_combo.set_active(0)
        try:
            interfaces = list_network_interfaces()
            for iface in interfaces:
                self._direct_interface_combo.append_text(iface)
        except Exception:
            pass
        connection_grid.attach(self._direct_interface_combo, 1, 2, 1, 1)

        self._vpn_auto_connect_check = Gtk.CheckButton(label="Подключать VPN при запуске профиля")
        self._vpn_auto_connect_check.set_tooltip_text(
            "Перед запуском профиля автоматически выполнять включать VPN"
        )
        connection_grid.attach(self._vpn_auto_connect_check, 0, 3, 2, 1)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_margin_start(10)
        status_box.set_margin_end(10)
        status_box.set_margin_top(5)
        status_box.set_margin_bottom(5)
        connection_frame.add(status_box)
        
        status_label = Gtk.Label(label="Статус:")
        status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(status_label, False, False, 0)
        
        self._vpn_status_label = Gtk.Label()
        self._vpn_status_label.set_halign(Gtk.Align.START)
        status_box.pack_start(self._vpn_status_label, True, True, 0)
        
        refresh_btn = Gtk.Button(label="Обновить")
        refresh_btn.connect("clicked", self._on_vpn_refresh_clicked)
        status_box.pack_end(refresh_btn, False, False, 0)

        networks_frame = Gtk.Frame()
        networks_frame.set_label("Подсети")
        box.pack_start(networks_frame, True, True, 0)
        
        networks_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        networks_box.set_margin_start(10)
        networks_box.set_margin_end(10)
        networks_box.set_margin_top(10)
        networks_box.set_margin_bottom(10)
        networks_frame.add(networks_box)
        
        networks_hint = Gtk.Label()
        networks_hint.set_markup(
            "<small>Укажите подсети и домены, которые должны маршрутизироваться через VPN.\n"
            "Одна запись на строку. Примеры:\n"
            "  • <tt>10.0.0.0/8</tt> — IP подсеть\n"
            "  • <tt>172.16.0.0/12</tt> — IP подсеть\n"
            "  • <tt>my.example.com</tt> — домен</small>"
        )
        networks_hint.set_halign(Gtk.Align.START)
        networks_hint.get_style_context().add_class("dim-label")
        networks_box.pack_start(networks_hint, False, False, 0)
        
        networks_scroll = Gtk.ScrolledWindow()
        networks_scroll.set_shadow_type(Gtk.ShadowType.IN)
        networks_scroll.set_min_content_height(200)
        self._vpn_networks_text = Gtk.TextView()
        self._vpn_networks_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._vpn_networks_text.modify_font(Pango.FontDescription("monospace 10"))
        networks_scroll.add(self._vpn_networks_text)
        networks_box.pack_start(networks_scroll, True, True, 0)
        
        # Direct access lists
        direct_frame = Gtk.Frame()
        direct_frame.set_label("Прямой доступ (без прокси и VPN)")
        box.pack_start(direct_frame, True, True, 0)

        direct_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        direct_box.set_margin_start(10)
        direct_box.set_margin_end(10)
        direct_box.set_margin_top(10)
        direct_box.set_margin_bottom(10)
        direct_frame.add(direct_box)

        direct_hint = Gtk.Label()
        direct_hint.set_markup(
            "<small>Укажите подсети и домены, которые должны всегда идти напрямую, "
            "без использования VPN/прокси.\n"
            "Одна запись на строку. Примеры:\n"
            "  • <tt>gosuslugi.ru</tt>\n"
            "  • <tt>provider.portal.local</tt>\n"
            "  • <tt>100.64.0.0/10</tt></small>"
        )
        direct_hint.set_halign(Gtk.Align.START)
        direct_hint.get_style_context().add_class("dim-label")
        direct_box.pack_start(direct_hint, False, False, 0)

        direct_scroll = Gtk.ScrolledWindow()
        direct_scroll.set_shadow_type(Gtk.ShadowType.IN)
        direct_scroll.set_min_content_height(160)
        self._vpn_direct_text = Gtk.TextView()
        self._vpn_direct_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._vpn_direct_text.modify_font(Pango.FontDescription("monospace 10"))
        direct_scroll.add(self._vpn_direct_text)
        direct_box.pack_start(direct_scroll, True, True, 0)

        scrolled.add(box)
        content.show_all()
    
    def _on_vpn_enable_changed(self, check: Gtk.CheckButton) -> None:
        """VPN enable checkbox handler."""
        enabled = check.get_active()
        self._vpn_connection_entry.set_sensitive(enabled)
        self._vpn_interface_combo.set_sensitive(enabled)
        self._direct_interface_combo.set_sensitive(enabled)
        self._vpn_auto_connect_check.set_sensitive(enabled)
        self._vpn_networks_text.set_sensitive(enabled)
        self._vpn_direct_text.set_sensitive(enabled)
    
    def _on_vpn_refresh_clicked(self, button: Optional[Gtk.Button]) -> None:
        """Refresh VPN status."""
        connection_name = self._vpn_connection_entry.get_text().strip() or "aiso"
        is_active = is_vpn_active(connection_name)
        
        if is_active:
            interface = get_vpn_interface(connection_name)
            if interface:
                self._vpn_status_label.set_markup(
                    f"<span color='green'>●</span> <b>Подключено</b> (интерфейс: {interface})"
                )
            else:
                self._vpn_status_label.set_markup(
                    "<span color='green'>●</span> <b>Подключено</b> (интерфейс не определён)"
                )
        else:
            self._vpn_status_label.set_markup(
                "<span color='red'>●</span> <b>Не подключено</b>"
            )
    
    def _load_settings(self) -> None:
        """Load VPN settings from profile."""
        vpn = self._profile.vpn_settings
        
        if vpn is None:
            # Use defaults
            vpn = VpnSettings()
        
        self._vpn_enable_check.set_active(vpn.enabled)
        self._vpn_connection_entry.set_text(vpn.connection_name)

        vpn_interface = vpn.interface_name
        if vpn_interface:
            model = self._vpn_interface_combo.get_model()
            for i, row in enumerate(model):
                if row[0] == vpn_interface:
                    self._vpn_interface_combo.set_active(i)
                    break
            else:
                self._vpn_interface_combo.append_text(vpn_interface)
                self._vpn_interface_combo.set_active(len(model))
        else:
            self._vpn_interface_combo.set_active(0)

        direct_interface = getattr(vpn, "direct_interface", "") or ""
        if direct_interface:
            model = self._direct_interface_combo.get_model()
            for i, row in enumerate(model):
                if row[0] == direct_interface:
                    self._direct_interface_combo.set_active(i)
                    break
            else:
                self._direct_interface_combo.append_text(direct_interface)
                self._direct_interface_combo.set_active(len(model))
        else:
            self._direct_interface_combo.set_active(0)
        
        self._vpn_auto_connect_check.set_active(getattr(vpn, "auto_connect", False))

        all_networks = vpn.over_vpn_networks + vpn.over_vpn_domains
        networks_text = "\n".join(all_networks)
        self._vpn_networks_text.get_buffer().set_text(networks_text)
        
        # Direct access lists
        direct_networks = getattr(vpn, "direct_networks", []) or []
        direct_domains = getattr(vpn, "direct_domains", []) or []
        all_direct = direct_networks + direct_domains
        direct_text = "\n".join(all_direct)
        self._vpn_direct_text.get_buffer().set_text(direct_text)
        
        self._on_vpn_enable_changed(self._vpn_enable_check)
        self._on_vpn_refresh_clicked(None)
    
    def save_settings(self) -> bool:
        """Save VPN settings to profile.

        Returns:
            True if settings were saved successfully
        """
        # Create or update VPN settings
        if self._profile.vpn_settings is None:
            self._profile.vpn_settings = VpnSettings()
        
        vpn = self._profile.vpn_settings
        
        vpn.enabled = self._vpn_enable_check.get_active()
        vpn.connection_name = self._vpn_connection_entry.get_text().strip() or "aiso"
        
        vpn_interface_text = self._vpn_interface_combo.get_active_text()
        if vpn_interface_text and vpn_interface_text.strip() and vpn_interface_text.strip() != "Автоопределение":
            vpn.interface_name = vpn_interface_text.strip()
        else:
            vpn.interface_name = ""
        
        direct_interface_text = self._direct_interface_combo.get_active_text()
        if direct_interface_text and direct_interface_text.strip() and direct_interface_text.strip() != "Автоопределение":
            vpn.direct_interface = direct_interface_text.strip()
        else:
            vpn.direct_interface = ""
        
        vpn.auto_connect = self._vpn_auto_connect_check.get_active()

        # Validate VPN connection name if integration is enabled
        if vpn.enabled:
            try:
                available = list_vpn_connections()
            except Exception:
                available = []

            if available and vpn.connection_name not in available:
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="VPN подключение не найдено",
                )
                dialog.set_wmclass("tenga-proxy", "tenga-proxy")
                dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
                dialog.set_skip_taskbar_hint(True)
                dialog.format_secondary_text(
                    f"Подключение с именем \"{vpn.connection_name}\" "
                    "не найдено в NetworkManager.\n\n"
                    "Проверьте имя или создайте VPN-подключение в настройках сети."
                )
                dialog.run()
                dialog.destroy()
                return False

        networks_buffer = self._vpn_networks_text.get_buffer()
        start, end = networks_buffer.get_bounds()
        networks_text = networks_buffer.get_text(start, end, True)

        entries = [line.strip() for line in networks_text.split("\n") if line.strip()]
        vpn.over_vpn_domains, vpn.over_vpn_networks = self._routing.parse_entries(entries)

        direct_buffer = self._vpn_direct_text.get_buffer()
        start, end = direct_buffer.get_bounds()
        direct_text = direct_buffer.get_text(start, end, True)

        direct_entries = [line.strip() for line in direct_text.split("\n") if line.strip()]
        vpn.direct_domains, vpn.direct_networks = self._routing.parse_entries(direct_entries)
        
        return True


def show_profile_vpn_settings_dialog(
    profile: 'ProfileEntry',
    parent: Optional[Gtk.Window] = None,
    on_settings_applied: Optional[Callable[[int], None]] = None,
) -> bool:
    """
    Show VPN settings dialog for a profile.
    
    Args:
        profile: Profile entry to configure
        parent: Parent window
        on_settings_applied: Optional callback called after settings are applied.
                            Receives profile_id as argument.
        
    Returns:
        True if settings were applied
    """
    dialog = ProfileVpnSettingsDialog(profile, parent)
    applied = False
    
    while True:
        response = dialog.run()
        if response == Gtk.ResponseType.APPLY:
            if dialog.save_settings():
                applied = True
                if on_settings_applied:
                    try:
                        on_settings_applied(profile.id)
                    except Exception as e:
                        logger.exception("Error in on_settings_applied callback: %s", e)
                break
            continue
        else:
            break

    dialog.destroy()
    return applied
