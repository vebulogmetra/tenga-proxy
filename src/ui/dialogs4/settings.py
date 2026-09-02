"""Application settings (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.db.config import DnsProvider, ProxyMode

LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
DEFAULT_LOG_LEVEL = "info"
DEFAULT_TUN_NAME = "xray0"


class KeyedCombo:
    """An Adw.ComboRow addressed by string keys instead of indices.

    `Adw.ComboRow` работает индексами, а настройки хранятся строками; без
    общей обёртки каждое поле заводило бы свой список соответствий и рано или
    поздно они разъехались бы.
    """

    def __init__(self, title: str, keys: list[str], labels: dict[str, str]) -> None:
        self.keys = list(keys)
        model = Gtk.StringList()
        for key in self.keys:
            model.append(labels.get(key, key))
        self.row = Adw.ComboRow(title=title, model=model)

    def select(self, key: str) -> None:
        """Select a key, falling back to the first entry when unknown."""
        try:
            self.row.set_selected(self.keys.index(key))
        except ValueError:
            # Настройка могла прийти от другой версии приложения.
            self.row.set_selected(0)

    def selected(self) -> str:
        index = self.row.get_selected()
        if 0 <= index < len(self.keys):
            return self.keys[index]
        return self.keys[0]


class SettingsDialog(Adw.PreferencesDialog):
    """Inbound, runtime mode, monitoring, DNS and logs."""

    __gtype_name__ = "TengaSettingsDialog"

    __gsignals__ = {
        "settings-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, config, context=None) -> None:
        super().__init__()
        self.set_title("Настройки")
        self._config = config
        self._context = context

        self._build_general_page()
        self._build_monitoring_page()
        self._build_dns_page()
        self._build_about_page()

        self._load()

    # --- страницы ---

    def _build_general_page(self) -> None:
        page = Adw.PreferencesPage(title="Общие", icon_name="preferences-system-symbolic")
        self.add(page)

        inbound = Adw.PreferencesGroup(
            title="Входящее соединение",
            description="Локальные порты SOCKS и HTTP",
        )
        page.add(inbound)

        self.address_row = Adw.EntryRow(title="Адрес")
        inbound.add(self.address_row)

        self.port_row = Adw.SpinRow.new_with_range(1024, 65535, 1)
        self.port_row.set_title("Порт SOCKS")
        self.port_row.set_subtitle("HTTP занимает следующий порт")
        inbound.add(self.port_row)

        runtime = Adw.PreferencesGroup(title="Режим работы")
        page.add(runtime)

        self._mode = KeyedCombo("Режим", ProxyMode.ALL, ProxyMode.LABELS)
        self.mode_row = self._mode.row
        self.mode_row.connect("notify::selected", lambda *_: self._sync_mode())
        runtime.add(self.mode_row)

        self.tun_name_row = Adw.EntryRow(title="Имя интерфейса TUN")
        runtime.add(self.tun_name_row)

        self.tun_mtu_row = Adw.SpinRow.new_with_range(576, 9000, 1)
        self.tun_mtu_row.set_title("MTU")
        runtime.add(self.tun_mtu_row)

        logs = Adw.PreferencesGroup(title="Журнал")
        page.add(logs)

        self._log_level = KeyedCombo(
            "Уровень подробности", LOG_LEVELS, {level: level for level in LOG_LEVELS}
        )
        self.log_level_row = self._log_level.row
        logs.add(self.log_level_row)

    def _build_monitoring_page(self) -> None:
        page = Adw.PreferencesPage(
            title="Мониторинг", icon_name="utilities-system-monitor-symbolic"
        )
        self.add(page)

        group = Adw.PreferencesGroup(
            title="Проверка соединения",
            description="Периодический опрос прокси и VPN",
        )
        page.add(group)

        self.monitoring_row = Adw.SwitchRow(title="Включить мониторинг")
        self.monitoring_row.connect("notify::active", lambda *_: self._sync_monitoring())
        group.add(self.monitoring_row)

        self.interval_row = Adw.SpinRow.new_with_range(5, 60, 1)
        self.interval_row.set_title("Интервал")
        self.interval_row.set_subtitle("Секунд между проверками")
        group.add(self.interval_row)

    def _build_dns_page(self) -> None:
        page = Adw.PreferencesPage(title="DNS", icon_name="network-server-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Провайдер")
        page.add(group)

        self._dns = KeyedCombo("DNS-сервер", DnsProvider.ALL, DnsProvider.LABELS)
        self.dns_row = self._dns.row
        group.add(self.dns_row)

        custom = Adw.PreferencesGroup(
            title="Свой адрес",
            description="Непустое поле перекрывает выбранного провайдера. "
            "Примеры: 8.8.8.8, https://dns.google/dns-query, tls://dns.google",
        )
        page.add(custom)

        self.dns_url_row = Adw.EntryRow(title="Адрес DNS")
        custom.add(self.dns_url_row)

        options = Adw.PreferencesGroup(title="Опции")
        page.add(options)

        self.dns_proxy_row = Adw.SwitchRow(
            title="Запросы через прокси",
            subtitle="Помогает обойти блокировки на уровне DNS",
        )
        options.add(self.dns_proxy_row)

    def _build_about_page(self) -> None:
        page = Adw.PreferencesPage(title="О программе", icon_name="help-about-symbolic")
        self.add(page)

        group = Adw.PreferencesGroup(title="Tenga Proxy")
        page.add(group)

        group.add(self._value_row("Версия", _app_version()))
        if self._context is not None:
            group.add(self._value_row("Конфигурация", str(self._context.config_dir)))

        actions = Adw.PreferencesGroup(title="Обслуживание")
        page.add(actions)

        self.clear_logs_row = Adw.ActionRow(
            title="Очистить журналы", subtitle="Удаляет накопленные файлы логов"
        )
        clear = Gtk.Button(label="Очистить", valign=Gtk.Align.CENTER)
        clear.add_css_class("destructive-action")
        clear.connect("clicked", self._on_clear_logs)
        self.clear_logs_row.add_suffix(clear)
        self.clear_logs_row.set_sensitive(self._context is not None)
        actions.add(self.clear_logs_row)

    @staticmethod
    def _value_row(title: str, value: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=value)
        row.set_subtitle_selectable(True)
        return row

    # --- состояние ---

    def _sync_mode(self) -> None:
        tun = self._mode.selected() == ProxyMode.TUN
        self.tun_name_row.set_sensitive(tun)
        self.tun_mtu_row.set_sensitive(tun)

    def _sync_monitoring(self) -> None:
        self.interval_row.set_sensitive(self.monitoring_row.get_active())

    def _load(self) -> None:
        config = self._config

        self.address_row.set_text(config.inbound_address)
        self.port_row.set_value(float(config.inbound_socks_port))

        self._mode.select(getattr(config, "proxy_mode", ProxyMode.TUN))
        self.tun_name_row.set_text(getattr(config, "tun_name", DEFAULT_TUN_NAME))
        self.tun_mtu_row.set_value(float(getattr(config, "tun_mtu", 1500)))
        self._sync_mode()

        self._log_level.select(getattr(config, "log_level", DEFAULT_LOG_LEVEL))

        monitoring = config.monitoring
        self.monitoring_row.set_active(monitoring.enabled)
        self.interval_row.set_value(float(monitoring.check_interval_seconds))
        self._sync_monitoring()

        dns = config.dns
        self._dns.select(dns.provider)
        self.dns_url_row.set_text(dns.custom_url)
        self.dns_proxy_row.set_active(dns.use_proxy)

    def save(self) -> None:
        """Write the form back into the configuration object."""
        config = self._config

        config.inbound_address = self.address_row.get_text().strip()
        config.inbound_socks_port = int(self.port_row.get_value())

        config.proxy_mode = self._mode.selected()
        # Безымянный интерфейс не создать — возвращаем значение по умолчанию.
        config.tun_name = self.tun_name_row.get_text().strip() or DEFAULT_TUN_NAME
        config.tun_mtu = int(self.tun_mtu_row.get_value())

        config.log_level = self._log_level.selected()

        config.monitoring.enabled = self.monitoring_row.get_active()
        config.monitoring.check_interval_seconds = int(self.interval_row.get_value())

        config.dns.provider = self._dns.selected()
        config.dns.custom_url = self.dns_url_row.get_text().strip()
        config.dns.use_proxy = self.dns_proxy_row.get_active()

        self.emit("settings-saved")

    # --- вспомогательное для тестов и внешнего кода ---

    def selected_mode(self) -> str:
        return self._mode.selected()

    def select_mode(self, key: str) -> None:
        self._mode.select(key)
        self._sync_mode()

    def select_dns(self, key: str) -> None:
        self._dns.select(key)

    def select_log_level(self, key: str) -> None:
        self._log_level.select(key)

    def _on_clear_logs(self, _button: Gtk.Button) -> None:
        if self._context is None:
            return
        removed, _size = self._context.log_manager.clear_all_logs()
        self.clear_logs_row.set_subtitle(f"Удалено файлов: {removed}")


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("tenga-proxy")
    except Exception:
        # В dev-режиме пакет может быть не установлен — версия не критична.
        return "—"
