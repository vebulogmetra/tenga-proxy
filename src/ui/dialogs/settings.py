from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Pango

from src.db.config import RoutingMode, DnsProvider

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.settings")


class SettingsDialog(Gtk.Dialog):
    """Application settings dialog."""
    
    def __init__(self, context: 'AppContext', parent: Optional[Gtk.Window] = None):
        super().__init__(
            title="Настройки",
            transient_for=parent,
            flags=0,
        )
        
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_APPLY, Gtk.ResponseType.APPLY,
        )
        
        self.set_default_size(650, 550)
        self.set_modal(True)
        
        self._context = context
        self._core_dir = context.config_dir
        
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        content = self.get_content_area()
        content.set_spacing(0)
        
        # Notebook with tabs
        notebook = Gtk.Notebook()
        content.pack_start(notebook, True, True, 0)
        # Tab: General
        general_page = self._create_general_page()
        notebook.append_page(general_page, Gtk.Label(label="Основные"))
        # Tab: DNS
        dns_page = self._create_dns_page()
        notebook.append_page(dns_page, Gtk.Label(label="DNS"))
        # Tab: Routing
        routing_page = self._create_routing_page()
        notebook.append_page(routing_page, Gtk.Label(label="Маршрутизация"))
        
        content.show_all()
    
    def _create_routing_page(self) -> Gtk.Widget:
        """Create routing settings page."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)
        
        # Routing modes
        mode_frame = Gtk.Frame()
        mode_frame.set_label("Режим маршрутизации")
        box.pack_start(mode_frame, False, False, 0)
        
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mode_box.set_margin_start(10)
        mode_box.set_margin_end(10)
        mode_box.set_margin_top(10)
        mode_box.set_margin_bottom(10)
        mode_frame.add(mode_box)
        
        self._mode_radios = {}
        first_radio = None
        
        for mode in RoutingMode.ALL:
            if first_radio is None:
                radio = Gtk.RadioButton.new_with_label(None, RoutingMode.LABELS[mode])
                first_radio = radio
            else:
                radio = Gtk.RadioButton.new_with_label_from_widget(first_radio, RoutingMode.LABELS[mode])
            
            radio.connect("toggled", self._on_mode_changed)
            self._mode_radios[mode] = radio
            
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.pack_start(radio, False, False, 0)
            
            desc = Gtk.Label()
            desc.set_markup(f"<small>{RoutingMode.DESCRIPTIONS[mode]}</small>")
            desc.set_halign(Gtk.Align.START)
            desc.set_margin_start(25)
            desc.get_style_context().add_class("dim-label")
            row.pack_start(desc, False, False, 0)
            
            mode_box.pack_start(row, False, False, 0)
        
        # List files (visible only in CUSTOM mode)
        self._lists_frame = Gtk.Frame()
        self._lists_frame.set_label("Пользовательские списки")
        box.pack_start(self._lists_frame, True, True, 0)
        
        lists_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lists_box.set_margin_start(10)
        lists_box.set_margin_end(10)
        lists_box.set_margin_top(10)
        lists_box.set_margin_bottom(10)
        self._lists_frame.add(lists_box)
        
        # Location info
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        lists_box.pack_start(info_box, False, False, 0)
        
        info_label = Gtk.Label()
        info_label.set_markup(f"<small>Расположение: <b>{self._core_dir}</b></small>")
        info_label.set_halign(Gtk.Align.START)
        info_label.set_selectable(True)
        info_box.pack_start(info_label, True, True, 0)
        
        open_folder_btn = Gtk.Button(label="Открыть папку")
        open_folder_btn.connect("clicked", self._on_open_folder_clicked)
        info_box.pack_end(open_folder_btn, False, False, 0)
        
        # Two columns for editors
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        lists_box.pack_start(paned, True, True, 0)
        
        # Left column — proxy_list.txt
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        paned.pack1(left_box, True, True)
        
        proxy_label = Gtk.Label()
        proxy_label.set_markup("<b>proxy_list.txt</b> <small>(через прокси)</small>")
        proxy_label.set_halign(Gtk.Align.START)
        left_box.pack_start(proxy_label, False, False, 0)
        
        proxy_scroll = Gtk.ScrolledWindow()
        proxy_scroll.set_shadow_type(Gtk.ShadowType.IN)
        proxy_scroll.set_min_content_height(200)
        self._proxy_text = Gtk.TextView()
        self._proxy_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._proxy_text.modify_font(Pango.FontDescription("monospace 10"))
        proxy_scroll.add(self._proxy_text)
        left_box.pack_start(proxy_scroll, True, True, 0)
        
        # Right column — direct_list.txt
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        paned.pack2(right_box, True, True)
        
        direct_label = Gtk.Label()
        direct_label.set_markup("<b>direct_list.txt</b> <small>(напрямую)</small>")
        direct_label.set_halign(Gtk.Align.START)
        right_box.pack_start(direct_label, False, False, 0)
        
        direct_scroll = Gtk.ScrolledWindow()
        direct_scroll.set_shadow_type(Gtk.ShadowType.IN)
        direct_scroll.set_min_content_height(200)
        self._direct_text = Gtk.TextView()
        self._direct_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._direct_text.modify_font(Pango.FontDescription("monospace 10"))
        direct_scroll.add(self._direct_text)
        right_box.pack_start(direct_scroll, True, True, 0)
        
        return box
    
    def _create_general_page(self) -> Gtk.Widget:
        """Create general settings page."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)
        
        # Proxy settings
        proxy_frame = Gtk.Frame()
        proxy_frame.set_label("Локальный прокси")
        box.pack_start(proxy_frame, False, False, 0)
        
        proxy_grid = Gtk.Grid()
        proxy_grid.set_row_spacing(8)
        proxy_grid.set_column_spacing(10)
        proxy_grid.set_margin_start(10)
        proxy_grid.set_margin_end(10)
        proxy_grid.set_margin_top(10)
        proxy_grid.set_margin_bottom(10)
        proxy_frame.add(proxy_grid)
        
        proxy_grid.attach(Gtk.Label(label="Адрес:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._address_entry = Gtk.Entry()
        self._address_entry.set_width_chars(15)
        proxy_grid.attach(self._address_entry, 1, 0, 1, 1)
        
        proxy_grid.attach(Gtk.Label(label="Порт:", halign=Gtk.Align.END), 2, 0, 1, 1)
        self._port_spin = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        proxy_grid.attach(self._port_spin, 3, 0, 1, 1)
        
        # Logging
        log_frame = Gtk.Frame()
        log_frame.set_label("Логирование")
        box.pack_start(log_frame, False, False, 0)
        
        log_grid = Gtk.Grid()
        log_grid.set_row_spacing(8)
        log_grid.set_column_spacing(10)
        log_grid.set_margin_start(10)
        log_grid.set_margin_end(10)
        log_grid.set_margin_top(10)
        log_grid.set_margin_bottom(10)
        log_frame.add(log_grid)
        
        log_grid.attach(Gtk.Label(label="Уровень:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._log_combo = Gtk.ComboBoxText()
        for level in ["trace", "debug", "info", "warn", "error", "fatal", "panic"]:
            self._log_combo.append_text(level)
        log_grid.attach(self._log_combo, 1, 0, 1, 1)
        
        # Empty space
        box.pack_start(Gtk.Box(), True, True, 0)
        
        return box
    
    def _create_dns_page(self) -> Gtk.Widget:
        """Create DNS settings page."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)
        
        # DNS provider
        provider_frame = Gtk.Frame()
        provider_frame.set_label("DNS провайдер")
        box.pack_start(provider_frame, False, False, 0)
        
        provider_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        provider_box.set_margin_start(10)
        provider_box.set_margin_end(10)
        provider_box.set_margin_top(10)
        provider_box.set_margin_bottom(10)
        provider_frame.add(provider_box)
        
        self._dns_radios = {}
        first_radio = None
        
        for provider in DnsProvider.ALL:
            if first_radio is None:
                radio = Gtk.RadioButton.new_with_label(None, DnsProvider.LABELS[provider])
                first_radio = radio
            else:
                radio = Gtk.RadioButton.new_with_label_from_widget(first_radio, DnsProvider.LABELS[provider])
            
            radio.connect("toggled", self._on_dns_provider_changed)
            self._dns_radios[provider] = radio
            
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.pack_start(radio, False, False, 0)
            
            # Show URL for DoH providers
            url = DnsProvider.URLS.get(provider, "")
            if url and url != "local":
                url_label = Gtk.Label()
                url_label.set_markup(f"<small><tt>{url}</tt></small>")
                url_label.get_style_context().add_class("dim-label")
                row.pack_start(url_label, False, False, 0)
            
            provider_box.pack_start(row, False, False, 0)
        
        # Custom DNS
        custom_frame = Gtk.Frame()
        custom_frame.set_label("Пользовательский DNS (вместо выбранного провайдера)")
        box.pack_start(custom_frame, False, False, 0)
        
        custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        custom_box.set_margin_start(10)
        custom_box.set_margin_end(10)
        custom_box.set_margin_top(10)
        custom_box.set_margin_bottom(10)
        custom_frame.add(custom_box)
        
        custom_hint = Gtk.Label()
        custom_hint.set_markup("<small>Оставьте пустым для использования выбранного провайдера</small>")
        custom_hint.set_halign(Gtk.Align.START)
        custom_hint.get_style_context().add_class("dim-label")
        custom_box.pack_start(custom_hint, False, False, 0)
        
        self._dns_custom_entry = Gtk.Entry()
        self._dns_custom_entry.set_placeholder_text("https://dns.example.com/dns-query")
        custom_box.pack_start(self._dns_custom_entry, False, False, 0)
        
        examples_label = Gtk.Label()
        examples_label.set_markup(
            "<small>Примеры:\n"
            "  • <tt>8.8.8.8</tt> — обычный UDP DNS\n"
            "  • <tt>https://dns.google/dns-query</tt> — DoH\n"
            "  • <tt>tls://dns.google</tt> — DoT</small>"
        )
        examples_label.set_halign(Gtk.Align.START)
        examples_label.get_style_context().add_class("dim-label")
        custom_box.pack_start(examples_label, False, False, 0)
        
        # Options
        options_frame = Gtk.Frame()
        options_frame.set_label("Опции")
        box.pack_start(options_frame, False, False, 0)
        
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        options_box.set_margin_start(10)
        options_box.set_margin_end(10)
        options_box.set_margin_top(10)
        options_box.set_margin_bottom(10)
        options_frame.add(options_box)
        
        self._dns_use_proxy_check = Gtk.CheckButton(label="DNS запросы через прокси")
        self._dns_use_proxy_check.set_tooltip_text(
            "Отправлять DNS запросы через прокси-сервер.\n"
            "Рекомендуется для обхода DNS-блокировок."
        )
        options_box.pack_start(self._dns_use_proxy_check, False, False, 0)
        
        # Empty space
        box.pack_start(Gtk.Box(), True, True, 0)
        
        return box
    
    def _on_dns_provider_changed(self, radio: Gtk.RadioButton) -> None:
        """DNS provider change handler."""
        pass  # Do nothing for now
    
    def _on_mode_changed(self, radio: Gtk.RadioButton) -> None:
        """Mode change handler."""
        if not radio.get_active():
            return
        
        for mode, r in self._mode_radios.items():
            if r.get_active():
                self._lists_frame.set_visible(mode == RoutingMode.CUSTOM)
                break
    
    def _on_open_folder_clicked(self, button: Gtk.Button) -> None:
        """Open folder with files."""
        import subprocess
        try:
            subprocess.Popen(["xdg-open", str(self._core_dir)])
        except Exception as e:
            logger.error("Failed to open folder: %s", e)
    
    def _load_settings(self) -> None:
        """Load current settings."""
        config = self._context.config
        routing = config.routing
        dns = config.dns
        
        # Routing mode
        mode = routing.mode
        if mode in self._mode_radios:
            self._mode_radios[mode].set_active(True)
        
        # Load files
        proxy_file = self._core_dir / "proxy_list.txt"
        direct_file = self._core_dir / "direct_list.txt"
        
        if proxy_file.exists():
            try:
                self._proxy_text.get_buffer().set_text(
                    proxy_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        
        if direct_file.exists():
            try:
                self._direct_text.get_buffer().set_text(
                    direct_file.read_text(encoding="utf-8")
                )
            except Exception:
                pass
        
        # Show/hide lists
        self._lists_frame.set_visible(mode == RoutingMode.CUSTOM)
        
        # General settings
        self._address_entry.set_text(config.inbound_address)
        self._port_spin.set_value(config.inbound_socks_port)
        
        # Log level
        log_levels = ["trace", "debug", "info", "warn", "error", "fatal", "panic"]
        if config.log_level in log_levels:
            self._log_combo.set_active(log_levels.index(config.log_level))
        else:
            self._log_combo.set_active(2)  # info
        
        # DNS settings
        if dns.provider in self._dns_radios:
            self._dns_radios[dns.provider].set_active(True)
        self._dns_custom_entry.set_text(dns.custom_url)
        self._dns_use_proxy_check.set_active(dns.use_proxy)
    
    def save_settings(self) -> None:
        """Save settings."""
        config = self._context.config
        routing = config.routing
        dns = config.dns
        
        # Routing mode
        for mode, radio in self._mode_radios.items():
            if radio.get_active():
                routing.mode = mode
                break
        
        # Save files
        proxy_file = self._core_dir / "proxy_list.txt"
        direct_file = self._core_dir / "direct_list.txt"
        
        proxy_buffer = self._proxy_text.get_buffer()
        start, end = proxy_buffer.get_bounds()
        proxy_text = proxy_buffer.get_text(start, end, True)
        
        direct_buffer = self._direct_text.get_buffer()
        start, end = direct_buffer.get_bounds()
        direct_text = direct_buffer.get_text(start, end, True)
        
        try:
            proxy_file.write_text(proxy_text, encoding="utf-8")
            direct_file.write_text(direct_text, encoding="utf-8")
        except Exception as e:
            logger.error("Error saving files: %s", e)
        
        # General settings
        config.inbound_address = self._address_entry.get_text().strip()
        config.inbound_socks_port = int(self._port_spin.get_value())
        
        log_levels = ["trace", "debug", "info", "warn", "error", "fatal", "panic"]
        config.log_level = log_levels[self._log_combo.get_active()]
        
        # DNS settings
        for provider, radio in self._dns_radios.items():
            if radio.get_active():
                dns.provider = provider
                break
        dns.custom_url = self._dns_custom_entry.get_text().strip()
        dns.use_proxy = self._dns_use_proxy_check.get_active()
        
        # Save
        self._context.save_config()


def show_settings_dialog(context: 'AppContext', parent: Optional[Gtk.Window] = None) -> bool:
    """
    Show settings dialog.
    
    Returns:
        True if settings were applied
    """
    dialog = SettingsDialog(context, parent)
    response = dialog.run()
    
    applied = False
    if response == Gtk.ResponseType.APPLY:
        dialog.save_settings()
        applied = True
    
    dialog.destroy()
    return applied
