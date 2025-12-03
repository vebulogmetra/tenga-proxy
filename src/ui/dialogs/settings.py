from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Pango

from src.db.config import DnsProvider
from src.sys.vpn import is_vpn_active, get_vpn_interface, list_vpn_connections

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
        # Tab: VPN & routes
        vpn_page = self._create_vpn_page()
        notebook.append_page(vpn_page, Gtk.Label(label="VPN и маршруты"))
        
        content.show_all()


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
    
    def _create_vpn_page(self) -> Gtk.Widget:
        """Create VPN settings page."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

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
        
        connection_grid.attach(Gtk.Label(label="Интерфейс:", halign=Gtk.Align.END), 0, 1, 1, 1)
        self._vpn_interface_entry = Gtk.Entry()
        self._vpn_interface_entry.set_placeholder_text("Автоопределение")
        self._vpn_interface_entry.set_tooltip_text("Имя интерфейса VPN. Оставьте пустым для автоопределения.")
        connection_grid.attach(self._vpn_interface_entry, 1, 1, 1, 1)

        self._vpn_auto_connect_check = Gtk.CheckButton(label="Подключать VPN при запуске профиля")
        self._vpn_auto_connect_check.set_tooltip_text(
            "Перед запуском профиля автоматически выполнять включать VPN"
        )
        connection_grid.attach(self._vpn_auto_connect_check, 0, 2, 2, 1)

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

        return scrolled
    
    def _on_vpn_enable_changed(self, check: Gtk.CheckButton) -> None:
        """VPN enable checkbox handler."""
        enabled = check.get_active()
        self._vpn_connection_entry.set_sensitive(enabled)
        self._vpn_interface_entry.set_sensitive(enabled)
        self._vpn_networks_text.set_sensitive(enabled)
    
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
    
    def _on_dns_provider_changed(self, radio: Gtk.RadioButton) -> None:
        """DNS provider change handler."""
        pass  # Do nothing for now

    
    def _load_settings(self) -> None:
        """Load current settings."""
        config = self._context.config
        dns = config.dns
        
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
        
        # VPN settings
        vpn = config.vpn
        self._vpn_enable_check.set_active(vpn.enabled)
        self._vpn_connection_entry.set_text(vpn.connection_name)
        self._vpn_interface_entry.set_text(vpn.interface_name)
        self._vpn_auto_connect_check.set_active(getattr(vpn, "auto_connect", False))

        all_networks = vpn.corporate_networks + vpn.corporate_domains
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
        """Save settings.

        Returns:
            True if settings were saved successfully
        """
        config = self._context.config
        dns = config.dns
        
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
        
        # VPN settings
        vpn = config.vpn
        vpn.enabled = self._vpn_enable_check.get_active()
        vpn.connection_name = self._vpn_connection_entry.get_text().strip() or "aiso"
        vpn.interface_name = self._vpn_interface_entry.get_text().strip()
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
        vpn.corporate_domains, vpn.corporate_networks = config.routing.parse_entries(entries)

        direct_buffer = self._vpn_direct_text.get_buffer()
        start, end = direct_buffer.get_bounds()
        direct_text = direct_buffer.get_text(start, end, True)

        direct_entries = [line.strip() for line in direct_text.split("\n") if line.strip()]
        vpn.direct_domains, vpn.direct_networks = config.routing.parse_entries(direct_entries)
        
        # Save
        self._context.save_config()
        return True


def show_settings_dialog(context: 'AppContext', parent: Optional[Gtk.Window] = None) -> bool:
    """
    Show settings dialog.
    
    Returns:
        True if settings were applied
    """
    dialog = SettingsDialog(context, parent)
    applied = False
    while True:
        response = dialog.run()
        if response == Gtk.ResponseType.APPLY:
            if dialog.save_settings():
                applied = True
                break
            continue
        else:
            break

    dialog.destroy()
    return applied
