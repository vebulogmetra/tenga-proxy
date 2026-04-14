from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import gi
from src.db.config import RoutingMode

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

from src import __app_author__, __app_description__, __app_website__
from src import __app_name__ as APP_NAME
from src import __version__ as APP_VERSION
from src.db.config import DnsProvider, ProxyMode
from src.ui.style import style_dialog

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.settings")


class SettingsDialog(Gtk.Dialog):
    """Application settings dialog."""

    def __init__(self, context: AppContext, parent: Gtk.Window | None = None):
        super().__init__(
            title="Настройки",
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

        self.set_default_size(650, 550)
        self.set_modal(True)
        self.set_skip_taskbar_hint(True)

        self._context = context
        self._core_dir = context.config_dir

        self._setup_ui()
        self._load_settings()
        style_dialog(self)

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

        # Notebook with tabs
        notebook = Gtk.Notebook()
        content.pack_start(notebook, True, True, 0)
        # Tab: General
        general_page = self._create_general_page()
        notebook.append_page(general_page, Gtk.Label(label="Основные"))
        # Tab: Monitoring
        monitoring_page = self._create_monitoring_page()
        notebook.append_page(monitoring_page, Gtk.Label(label="Мониторинг"))
        # Tab: DNS
        dns_page = self._create_dns_page()
        notebook.append_page(dns_page, Gtk.Label(label="DNS"))
        # Tab: About
        about_page = self._create_about_page()
        notebook.append_page(about_page, Gtk.Label(label="О программе"))

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

        runtime_frame = Gtk.Frame()
        runtime_frame.set_label("Режим работы")
        box.pack_start(runtime_frame, False, False, 0)

        runtime_grid = Gtk.Grid()
        runtime_grid.set_row_spacing(8)
        runtime_grid.set_column_spacing(10)
        runtime_grid.set_margin_start(10)
        runtime_grid.set_margin_end(10)
        runtime_grid.set_margin_top(10)
        runtime_grid.set_margin_bottom(10)
        runtime_frame.add(runtime_grid)

        runtime_grid.attach(Gtk.Label(label="Режим:", halign=Gtk.Align.END), 0, 0, 1, 1)
        self._proxy_mode_combo = Gtk.ComboBoxText()
        self._proxy_mode_keys = [ProxyMode.TUN, ProxyMode.SYSTEM_PROXY]
        for mode in self._proxy_mode_keys:
            self._proxy_mode_combo.append_text(ProxyMode.LABELS[mode])
        self._proxy_mode_combo.set_active(0)
        self._proxy_mode_combo.connect("changed", self._on_proxy_mode_changed)
        runtime_grid.attach(self._proxy_mode_combo, 1, 0, 3, 1)

        runtime_grid.attach(
            Gtk.Label(label="TUN интерфейс:", halign=Gtk.Align.END), 0, 1, 1, 1
        )
        self._tun_name_entry = Gtk.Entry()
        self._tun_name_entry.set_placeholder_text("xray0")
        runtime_grid.attach(self._tun_name_entry, 1, 1, 1, 1)

        runtime_grid.attach(Gtk.Label(label="TUN MTU:", halign=Gtk.Align.END), 2, 1, 1, 1)
        self._tun_mtu_spin = Gtk.SpinButton.new_with_range(576, 9000, 1)
        runtime_grid.attach(self._tun_mtu_spin, 3, 1, 1, 1)

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

        # Add separator
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Log files management
        log_mgmt_frame = Gtk.Frame()
        log_mgmt_frame.set_label("Управление логами")
        box.pack_start(log_mgmt_frame, False, False, 0)

        log_mgmt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        log_mgmt_box.set_margin_start(10)
        log_mgmt_box.set_margin_end(10)
        log_mgmt_box.set_margin_top(10)
        log_mgmt_box.set_margin_bottom(10)
        log_mgmt_frame.add(log_mgmt_box)

        # Log size info
        self._log_info_label = Gtk.Label()
        self._log_info_label.set_halign(Gtk.Align.START)
        self._update_log_info_label()
        log_mgmt_box.pack_start(self._log_info_label, False, False, 0)

        # Clear logs button
        clear_logs_btn = Gtk.Button(label="Очистить все логи")
        clear_logs_btn.connect("clicked", self._on_clear_logs_clicked)
        clear_logs_btn.set_tooltip_text("Удалить все файлы логов для освобождения места")
        log_mgmt_box.pack_start(clear_logs_btn, False, False, 0)

        # Empty space
        box.pack_start(Gtk.Box(), True, True, 0)

        return box

    def _create_monitoring_page(self) -> Gtk.Widget:
        """Create monitoring settings page."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_top(15)
        box.set_margin_bottom(15)

        # Monitoring settings
        monitoring_frame = Gtk.Frame()
        monitoring_frame.set_label("Мониторинг соединений")
        box.pack_start(monitoring_frame, False, False, 0)

        monitoring_grid = Gtk.Grid()
        monitoring_grid.set_row_spacing(8)
        monitoring_grid.set_column_spacing(10)
        monitoring_grid.set_margin_start(10)
        monitoring_grid.set_margin_end(10)
        monitoring_grid.set_margin_top(10)
        monitoring_grid.set_margin_bottom(10)
        monitoring_frame.add(monitoring_grid)

        self._monitoring_enable_check = Gtk.CheckButton(label="Включить мониторинг соединений")
        self._monitoring_enable_check.set_tooltip_text(
            "Автоматически проверять статус прокси и VPN соединений и отправлять уведомления при изменениях"
        )
        monitoring_grid.attach(self._monitoring_enable_check, 0, 0, 2, 1)

        monitoring_grid.attach(
            Gtk.Label(label="Интервал проверки (сек):", halign=Gtk.Align.END), 0, 1, 1, 1
        )
        self._monitoring_interval_spin = Gtk.SpinButton.new_with_range(5, 60, 1)
        self._monitoring_interval_spin.set_tooltip_text(
            "Интервал между проверками статуса соединений (5-60 секунд)"
        )
        monitoring_grid.attach(self._monitoring_interval_spin, 1, 1, 1, 1)

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
                radio = Gtk.RadioButton.new_with_label_from_widget(
                    first_radio, DnsProvider.LABELS[provider]
                )

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
        custom_hint.set_markup(
            "<small>Оставьте пустым для использования выбранного провайдера</small>"
        )
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
            "Отправлять DNS запросы через прокси-сервер.\nРекомендуется для обхода DNS-блокировок."
        )
        options_box.pack_start(self._dns_use_proxy_check, False, False, 0)

        # Empty space
        box.pack_start(Gtk.Box(), True, True, 0)

        return box

    def _create_about_page(self) -> Gtk.Widget:
        """Create about page."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)
        box.set_margin_bottom(20)

        name_label = Gtk.Label()
        name_label.set_markup(f"<span size='xx-large' weight='bold'>{APP_NAME}</span>")
        name_label.set_halign(Gtk.Align.CENTER)
        box.pack_start(name_label, False, False, 0)

        version_label = Gtk.Label()
        version_label.set_markup(f"<span size='large'>Версия {APP_VERSION}</span>")
        version_label.set_halign(Gtk.Align.CENTER)
        box.pack_start(version_label, False, False, 0)

        desc_label = Gtk.Label()
        desc_label.set_markup(__app_description__)
        desc_label.set_line_wrap(True)
        desc_label.set_halign(Gtk.Align.CENTER)
        desc_label.set_max_width_chars(60)
        desc_label.set_use_markup(True)
        box.pack_start(desc_label, False, False, 0)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(separator, False, False, 10)

        info_frame = Gtk.Frame()
        info_frame.set_label("Информация")
        box.pack_start(info_frame, False, False, 0)

        info_grid = Gtk.Grid()
        info_grid.set_row_spacing(8)
        info_grid.set_column_spacing(15)
        info_grid.set_margin_start(15)
        info_grid.set_margin_end(15)
        info_grid.set_margin_top(15)
        info_grid.set_margin_bottom(15)
        info_frame.add(info_grid)

        info_grid.attach(Gtk.Label(label="Автор:", halign=Gtk.Align.START), 0, 0, 1, 1)
        author_label = Gtk.Label(label=__app_author__)
        author_label.set_halign(Gtk.Align.START)
        info_grid.attach(author_label, 1, 0, 1, 1)

        info_grid.attach(Gtk.Label(label="GitHub:", halign=Gtk.Align.START), 0, 1, 1, 1)
        website_label = Gtk.Label()
        website_label.set_markup(f"<a href='{__app_website__}'>{__app_website__}</a>")
        website_label.set_halign(Gtk.Align.START)
        website_label.set_use_markup(True)
        info_grid.attach(website_label, 1, 1, 1, 1)

        info_grid.attach(Gtk.Label(label="Лицензия:", halign=Gtk.Align.START), 0, 2, 1, 1)
        license_label = Gtk.Label(label="MIT License")
        license_label.set_halign(Gtk.Align.START)
        info_grid.attach(license_label, 1, 2, 1, 1)

        box.pack_start(Gtk.Box(), True, True, 0)

        scrolled.add(box)
        return scrolled

    def _on_dns_provider_changed(self, radio: Gtk.RadioButton) -> None:
        """DNS provider change handler."""
        # Do nothing for now

    def _on_proxy_mode_changed(self, combo: Gtk.ComboBoxText | None = None) -> None:
        """Toggle TUN-specific controls by selected proxy mode."""
        active_idx = self._proxy_mode_combo.get_active()
        mode = (
            self._proxy_mode_keys[active_idx]
            if active_idx is not None and 0 <= active_idx < len(self._proxy_mode_keys)
            else ProxyMode.TUN
        )
        tun_enabled = mode == ProxyMode.TUN
        self._tun_name_entry.set_sensitive(tun_enabled)
        self._tun_mtu_spin.set_sensitive(tun_enabled)

    def _load_settings(self) -> None:
        """Load current settings."""
        config = self._context.config
        dns = config.dns

        # General settings
        self._address_entry.set_text(config.inbound_address)
        self._port_spin.set_value(config.inbound_socks_port)
        config_mode = getattr(config, "proxy_mode", ProxyMode.TUN)
        if config_mode in self._proxy_mode_keys:
            self._proxy_mode_combo.set_active(self._proxy_mode_keys.index(config_mode))
        else:
            self._proxy_mode_combo.set_active(0)
        self._tun_name_entry.set_text(getattr(config, "tun_name", "xray0"))
        self._tun_mtu_spin.set_value(getattr(config, "tun_mtu", 1500))
        self._on_proxy_mode_changed()

        # Log level
        log_levels = ["trace", "debug", "info", "warn", "error", "fatal", "panic"]
        if config.log_level in log_levels:
            self._log_combo.set_active(log_levels.index(config.log_level))
        else:
            self._log_combo.set_active(2)  # info

        # Monitoring settings
        monitoring = config.monitoring
        self._monitoring_enable_check.set_active(monitoring.enabled)
        self._monitoring_interval_spin.set_value(monitoring.check_interval_seconds)

        # DNS settings
        if dns.provider in self._dns_radios:
            self._dns_radios[dns.provider].set_active(True)
        self._dns_custom_entry.set_text(dns.custom_url)
        self._dns_use_proxy_check.set_active(dns.use_proxy)

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
        mode_idx = self._proxy_mode_combo.get_active()
        if mode_idx is not None and 0 <= mode_idx < len(self._proxy_mode_keys):
            config.proxy_mode = self._proxy_mode_keys[mode_idx]
        else:
            config.proxy_mode = ProxyMode.TUN
        config.tun_name = self._tun_name_entry.get_text().strip() or "xray0"
        config.tun_mtu = int(self._tun_mtu_spin.get_value())

        log_levels = ["trace", "debug", "info", "warn", "error", "fatal", "panic"]
        config.log_level = log_levels[self._log_combo.get_active()]

        # Monitoring settings
        monitoring = config.monitoring
        monitoring.enabled = self._monitoring_enable_check.get_active()
        monitoring.check_interval_seconds = int(self._monitoring_interval_spin.get_value())

        # DNS settings
        for provider, radio in self._dns_radios.items():
            if radio.get_active():
                dns.provider = provider
                break
        dns.custom_url = self._dns_custom_entry.get_text().strip()
        dns.use_proxy = self._dns_use_proxy_check.get_active()

        # Save
        self._context.save_config()
        return True

    def _update_log_info_label(self) -> None:
        """Update the log info label with current size."""
        try:
            log_info = self._context.log_manager.get_logs_info()
            total_mb = log_info["total_size"] / (1024 * 1024)
            file_count = len(log_info["files"])

            self._log_info_label.set_markup(
                f"<b>Текущий размер логов:</b> {total_mb:.2f} МБ ({file_count} файлов)"
            )
        except Exception as e:
            logger.warning("Failed to get log info: %s", e)
            self._log_info_label.set_text("Не удалось получить информацию о логах")

    def _on_clear_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle clear logs button click."""
        try:
            log_info = self._context.log_manager.get_logs_info()
            total_mb = log_info["total_size"] / (1024 * 1024)
            file_count = len(log_info["files"])

            # Show confirmation dialog
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Очистить все логи?"
            )
            dialog.format_secondary_text(
                f"Это удалит {file_count} файлов логов и освободит {total_mb:.2f} МБ места.\n"
                "Это действие необратимо."
            )

            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.YES:
                # Clear logs
                file_count, bytes_freed = self._context.log_manager.clear_all_logs()
                mb_freed = bytes_freed / (1024 * 1024)

                # Update label
                self._update_log_info_label()

                # Show success message
                success_dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Логи успешно очищены"
                )
                success_dialog.format_secondary_text(
                    f"Удалено {file_count} файлов, освобождено {mb_freed:.2f} МБ"
                )
                success_dialog.run()
                success_dialog.destroy()

                logger.info("Logs cleared via UI: %d files, %.2f MB", file_count, mb_freed)

        except Exception as e:
            logger.exception("Failed to clear logs: %s", e)
            error_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Ошибка при очистке логов"
            )
            error_dialog.format_secondary_text(str(e))
            error_dialog.run()
            error_dialog.destroy()


def show_settings_dialog(
    context: AppContext,
    parent: Gtk.Window | None = None,
    on_config_reload: Callable[[], None] | None = None,
) -> bool:
    """
    Show settings dialog.

    Args:
        context: Application context
        parent: Parent window
        on_config_reload: Optional callback to reload configuration after saving

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
                # If proxy is running and reload callback is provided, reload config
                if context.proxy_state.is_running and on_config_reload:
                    try:
                        on_config_reload()
                    except Exception as e:
                        logger.exception("Error reloading configuration: %s", e)
                break
            continue
        break

    dialog.destroy()

    if applied and parent:

        def update_ui():
            if hasattr(parent, "_update_monitoring_tab_visibility"):
                parent._update_monitoring_tab_visibility()

        from gi.repository import GLib

        GLib.idle_add(update_ui)

    return applied
