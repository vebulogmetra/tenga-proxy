from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk, Pango

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.sys.vpn import (
    get_vpn_interface,
    is_vpn_active,
    list_network_interfaces,
    list_vpn_connections,
)

if TYPE_CHECKING:
    from src.db.profiles import ProfileEntry

logger = logging.getLogger("tenga.ui.profile_vpn_settings")


class ProfileVpnSettingsDialog(Gtk.Dialog):
    """VPN settings dialog for a specific profile."""

    def __init__(self, profile: ProfileEntry, parent: Gtk.Window | None = None):
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
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_APPLY,
            Gtk.ResponseType.APPLY,
        )

        self.set_default_size(650, 600)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)

        self._profile = profile
        self._routing = profile.routing_settings or RoutingSettings()

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

        notebook = Gtk.Notebook()
        content.pack_start(notebook, True, True, 0)

        # Profile settings
        profile_page = self._create_profile_page()
        notebook.append_page(profile_page, Gtk.Label(label="Профиль"))

        # VPN settings
        vpn_page = self._create_vpn_page()
        notebook.append_page(vpn_page, Gtk.Label(label="VPN"))

        # Routing settings
        routing_page = self._create_routing_page()
        notebook.append_page(routing_page, Gtk.Label(label="Маршруты"))

        content.show_all()

    def _create_profile_page(self) -> Gtk.Widget:
        """Create profile settings page."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)

        profile_frame = Gtk.Frame()
        profile_frame.set_label("Профиль")
        box.pack_start(profile_frame, False, False, 0)

        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        profile_box.set_margin_start(10)
        profile_box.set_margin_end(10)
        profile_box.set_margin_top(10)
        profile_box.set_margin_bottom(10)
        profile_frame.add(profile_box)

        name_grid = Gtk.Grid()
        name_grid.set_row_spacing(8)
        name_grid.set_column_spacing(10)
        profile_box.pack_start(name_grid, False, False, 0)

        name_grid.attach(
            Gtk.Label(label="Имя профиля:", halign=Gtk.Align.END), 0, 0, 1, 1
        )
        self._profile_name_entry = Gtk.Entry()
        self._profile_name_entry.set_text(self._profile.name)
        self._profile_name_entry.set_tooltip_text("Имя профиля для отображения в списке")
        name_grid.attach(self._profile_name_entry, 1, 0, 1, 1)

        box.pack_start(Gtk.Box(), True, True, 0)

        scrolled.add(box)
        return scrolled

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

        connection_grid.attach(
            Gtk.Label(label="Имя подключения:", halign=Gtk.Align.END), 0, 0, 1, 1
        )
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
        self._vpn_interface_combo.set_tooltip_text(
            "Выберите интерфейс VPN. 'Автоопределение' - автоматический выбор."
        )
        self._vpn_interface_combo.append_text("Автоопределение")
        self._vpn_interface_combo.set_active(0)
        try:
            interfaces = list_network_interfaces()
            for iface in interfaces:
                self._vpn_interface_combo.append_text(iface)
        except Exception:
            pass
        connection_grid.attach(self._vpn_interface_combo, 1, 1, 1, 1)

        connection_grid.attach(
            Gtk.Label(label="Интерфейс Direct:", halign=Gtk.Align.END), 0, 2, 1, 1
        )
        self._direct_interface_combo = Gtk.ComboBoxText()
        self._direct_interface_combo.set_tooltip_text(
            "Выберите интерфейс для прямого трафика (обход VPN). 'Автоопределение' - автоматический выбор."
        )
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

        box.pack_start(Gtk.Box(), True, True, 0)

        scrolled.add(box)
        return scrolled

    def _create_routing_page(self) -> Gtk.Widget:
        """Create routing settings page."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)

        mode_frame = Gtk.Frame()
        mode_frame.set_label("Режим роутинга")
        box.pack_start(mode_frame, False, False, 0)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mode_box.set_margin_start(10)
        mode_box.set_margin_end(10)
        mode_box.set_margin_top(10)
        mode_box.set_margin_bottom(10)
        mode_frame.add(mode_box)

        self._routing_radios = {}
        first_radio = None

        for mode in RoutingMode.ALL:
            if first_radio is None:
                radio = Gtk.RadioButton.new_with_label(None, RoutingMode.LABELS[mode])
                first_radio = radio
            else:
                radio = Gtk.RadioButton.new_with_label_from_widget(
                    first_radio, RoutingMode.LABELS[mode]
                )

            radio.connect("toggled", self._on_routing_mode_changed)
            self._routing_radios[mode] = radio

            desc_label = Gtk.Label()
            desc_label.set_markup(f"<small>{RoutingMode.DESCRIPTIONS[mode]}</small>")
            desc_label.set_halign(Gtk.Align.START)
            desc_label.get_style_context().add_class("dim-label")
            desc_label.set_margin_start(30)

            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.pack_start(radio, False, False, 0)
            row.pack_start(desc_label, False, False, 0)
            mode_box.pack_start(row, False, False, 0)

        lists_frame = Gtk.Frame()
        lists_frame.set_label("Списки роутинга (для режима 'Пользовательские списки')")
        box.pack_start(lists_frame, True, True, 0)

        lists_notebook = Gtk.Notebook()
        lists_notebook.set_margin_start(10)
        lists_notebook.set_margin_end(10)
        lists_notebook.set_margin_top(10)
        lists_notebook.set_margin_bottom(10)
        lists_frame.add(lists_notebook)

        proxy_scroll = Gtk.ScrolledWindow()
        proxy_scroll.set_shadow_type(Gtk.ShadowType.IN)
        proxy_scroll.set_min_content_height(200)
        self._proxy_list_text = Gtk.TextView()
        self._proxy_list_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._proxy_list_text.modify_font(Pango.FontDescription("monospace 10"))
        proxy_scroll.add(self._proxy_list_text)

        proxy_hint = Gtk.Label()
        proxy_hint.set_markup(
            "<small>Домены и IP-адреса, которые должны идти через прокси.\n"
            "Одна запись на строку. Примеры:\n"
            "  • <tt>example.com</tt>\n"
            "  • <tt>192.168.1.0/24</tt></small>"
        )
        proxy_hint.set_halign(Gtk.Align.START)
        proxy_hint.get_style_context().add_class("dim-label")

        proxy_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        proxy_box.set_margin_start(5)
        proxy_box.set_margin_end(5)
        proxy_box.set_margin_top(5)
        proxy_box.set_margin_bottom(5)
        proxy_box.pack_start(proxy_hint, False, False, 0)
        proxy_box.pack_start(proxy_scroll, True, True, 0)
        lists_notebook.append_page(proxy_box, Gtk.Label(label="Через прокси"))

        direct_scroll = Gtk.ScrolledWindow()
        direct_scroll.set_shadow_type(Gtk.ShadowType.IN)
        direct_scroll.set_min_content_height(200)
        self._direct_list_text = Gtk.TextView()
        self._direct_list_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._direct_list_text.modify_font(Pango.FontDescription("monospace 10"))
        direct_scroll.add(self._direct_list_text)

        direct_hint = Gtk.Label()
        direct_hint.set_markup(
            "<small>Домены и IP-адреса, которые должны идти напрямую (без прокси и VPN).\n"
            "Одна запись на строку. Примеры:\n"
            "  • <tt>local.example.com</tt>\n"
            "  • <tt>10.0.0.0/8</tt></small>"
        )
        direct_hint.set_halign(Gtk.Align.START)
        direct_hint.get_style_context().add_class("dim-label")

        direct_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        direct_box.set_margin_start(5)
        direct_box.set_margin_end(5)
        direct_box.set_margin_top(5)
        direct_box.set_margin_bottom(5)
        direct_box.pack_start(direct_hint, False, False, 0)

        self._bypass_local_check = Gtk.CheckButton(label="Добавить локальные сети")
        self._bypass_local_check.set_tooltip_text(
            "Автоматически добавлять локальные сети (127.0.0.0/8, 192.168.0.0/16, etc.) в список"
        )
        self._bypass_local_check.set_can_focus(False)
        self._bypass_local_check.connect("toggled", self._on_bypass_local_changed)
        direct_box.pack_start(self._bypass_local_check, False, False, 0)
        
        direct_box.pack_start(direct_scroll, True, True, 0)
        lists_notebook.append_page(direct_box, Gtk.Label(label="Напрямую"))

        vpn_scroll = Gtk.ScrolledWindow()
        vpn_scroll.set_shadow_type(Gtk.ShadowType.IN)
        vpn_scroll.set_min_content_height(200)
        self._vpn_list_text = Gtk.TextView()
        self._vpn_list_text.set_wrap_mode(Gtk.WrapMode.WORD)
        self._vpn_list_text.modify_font(Pango.FontDescription("monospace 10"))
        vpn_scroll.add(self._vpn_list_text)

        vpn_hint = Gtk.Label()
        vpn_hint.set_markup(
            "<small>Домены и IP-адреса, которые должны идти через VPN.\n"
            "Доступно только если включена интеграция VPN.\n"
            "Одна запись на строку. Примеры:\n"
            "  • <tt>vpn.example.com</tt>\n"
            "  • <tt>172.16.0.0/12</tt></small>"
        )
        vpn_hint.set_halign(Gtk.Align.START)
        vpn_hint.get_style_context().add_class("dim-label")

        vpn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vpn_box.set_margin_start(5)
        vpn_box.set_margin_end(5)
        vpn_box.set_margin_top(5)
        vpn_box.set_margin_bottom(5)
        vpn_box.pack_start(vpn_hint, False, False, 0)
        vpn_box.pack_start(vpn_scroll, True, True, 0)
        lists_notebook.append_page(vpn_box, Gtk.Label(label="Через VPN"))

        box.pack_start(Gtk.Box(), True, True, 0)

        scrolled.add(box)
        return scrolled

    def _on_routing_mode_changed(self, radio: Gtk.RadioButton | None) -> None:
        """Routing mode change handler."""
        if not hasattr(self, "_routing_radios") or not hasattr(self, "_proxy_list_text"):
            return

        is_custom = False
        for mode, r in self._routing_radios.items():
            if r.get_active() and mode == RoutingMode.CUSTOM:
                is_custom = True
                break

        self._proxy_list_text.set_sensitive(is_custom)
        self._direct_list_text.set_sensitive(is_custom)
        self._vpn_list_text.set_sensitive(True)
        if hasattr(self, "_bypass_local_check"):
            self._bypass_local_check.set_sensitive(is_custom)

    def _on_bypass_local_changed(self, check: Gtk.CheckButton) -> None:
        """Bypass local networks checkbox handler."""
        if not hasattr(self, "_direct_list_text"):
            return
        
        local_networks = [
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "169.254.0.0/16",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        ]
        
        buffer = self._direct_list_text.get_buffer()
        start, end = buffer.get_bounds()
        current_text = buffer.get_text(start, end, True)
        current_lines = [line.strip() for line in current_text.split("\n") if line.strip()]
        
        if check.get_active():
            for network in local_networks:
                if network not in current_lines:
                    current_lines.append(network)
        else:
            current_lines = [line for line in current_lines if line not in local_networks]
        
        buffer.set_text("\n".join(current_lines))

    def _on_vpn_enable_changed(self, check: Gtk.CheckButton) -> None:
        """VPN enable checkbox handler."""
        enabled = check.get_active()
        self._vpn_connection_entry.set_sensitive(enabled)
        self._vpn_interface_combo.set_sensitive(enabled)
        self._direct_interface_combo.set_sensitive(enabled)
        self._vpn_auto_connect_check.set_sensitive(enabled)

    def _on_vpn_refresh_clicked(self, button: Gtk.Button | None) -> None:
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
            self._vpn_status_label.set_markup("<span color='red'>●</span> <b>Не подключено</b>")

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

        # Load routing settings
        routing = self._profile.routing_settings
        if routing is None:
            routing = RoutingSettings()

        if hasattr(self, "_routing_radios") and routing.mode in self._routing_radios:
            self._routing_radios[routing.mode].set_active(True)

        if hasattr(self, "_proxy_list_text") and hasattr(self, "_direct_list_text") and hasattr(self, "_vpn_list_text"):
            self._proxy_list_text.get_buffer().set_text("\n".join(routing.proxy_list))
            self._direct_list_text.get_buffer().set_text("\n".join(routing.direct_list))
            self._vpn_list_text.get_buffer().set_text("\n".join(routing.vpn_list))

            if hasattr(self, "_bypass_local_check"):
                self._bypass_local_check.set_active(routing.bypass_local_networks)

            if hasattr(self, "_routing_radios"):
                self._on_routing_mode_changed(None)

        self._on_vpn_enable_changed(self._vpn_enable_check)
        self._on_vpn_refresh_clicked(None)

    def save_settings(self) -> bool:
        """Save VPN settings to profile.

        Returns:
            True if settings were saved successfully
        """
        profile_name = self._profile_name_entry.get_text().strip()
        if profile_name:
            self._profile.bean.name = profile_name

        # Create or update VPN settings
        if self._profile.vpn_settings is None:
            self._profile.vpn_settings = VpnSettings()

        vpn = self._profile.vpn_settings

        vpn.enabled = self._vpn_enable_check.get_active()
        vpn.connection_name = self._vpn_connection_entry.get_text().strip() or "aiso"

        vpn_interface_text = self._vpn_interface_combo.get_active_text()
        if (
            vpn_interface_text
            and vpn_interface_text.strip()
            and vpn_interface_text.strip() != "Автоопределение"
        ):
            vpn.interface_name = vpn_interface_text.strip()
        else:
            vpn.interface_name = ""

        direct_interface_text = self._direct_interface_combo.get_active_text()
        if (
            direct_interface_text
            and direct_interface_text.strip()
            and direct_interface_text.strip() != "Автоопределение"
        ):
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
                    f'Подключение с именем "{vpn.connection_name}" '
                    "не найдено в NetworkManager.\n\n"
                    "Проверьте имя или создайте VPN-подключение в настройках сети."
                )
                dialog.run()
                dialog.destroy()
                return False

        if self._profile.routing_settings is None:
            self._profile.routing_settings = RoutingSettings()

        routing = self._profile.routing_settings

        if hasattr(self, "_routing_radios"):
            for mode, radio in self._routing_radios.items():
                if radio.get_active():
                    routing.mode = mode
                    break

        if hasattr(self, "_proxy_list_text") and hasattr(self, "_direct_list_text") and hasattr(self, "_vpn_list_text"):
            proxy_buffer = self._proxy_list_text.get_buffer()
            start, end = proxy_buffer.get_bounds()
            proxy_text = proxy_buffer.get_text(start, end, True)
            routing.proxy_list = [line.strip() for line in proxy_text.split("\n") if line.strip()]

            direct_buffer = self._direct_list_text.get_buffer()
            start, end = direct_buffer.get_bounds()
            direct_text = direct_buffer.get_text(start, end, True)
            routing.direct_list = [line.strip() for line in direct_text.split("\n") if line.strip()]

            vpn_buffer = self._vpn_list_text.get_buffer()
            start, end = vpn_buffer.get_bounds()
            vpn_text = vpn_buffer.get_text(start, end, True)
            routing.vpn_list = [line.strip() for line in vpn_text.split("\n") if line.strip()]

            if hasattr(self, "_bypass_local_check"):
                routing.bypass_local_networks = self._bypass_local_check.get_active()

        return True


def show_profile_vpn_settings_dialog(
    profile: ProfileEntry,
    parent: Gtk.Window | None = None,
    on_settings_applied: Callable[[int], None] | None = None,
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
        break

    dialog.destroy()
    return applied
