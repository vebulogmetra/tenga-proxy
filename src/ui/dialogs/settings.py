"""Application settings (GTK4)."""

from __future__ import annotations

import copy
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from src.core.config import get_asset_path
from src.core.core_update import evaluate, fetch_releases, known_releases, refresh_known_releases
from src.core.geo import USER_GEO_DIR
from src.core.geo_update import update_geo_bases
from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
from src.sub.device import ensure_hwid
from src.sys import tun_access
from src.ui.logic import platform_texts
from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.platform_texts import (
    KILL_SWITCH_HINT,
    KILL_SWITCH_LABEL,
    kill_switch_available,
)
from src.ui.logic.routing_form import current_catalog, geo_summary
from src.ui.logic.settings_form import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_TUN_NAME,
    LOG_LEVELS,
    SAVE_IDLE,
    SAVE_PENDING,
    SETTINGS_SECTIONS,
    invalid_text,
    save_status_text,
    validate_settings,
)
from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
from src.ui.window import apply_theme

SETTINGS_WIDTH = 960
SETTINGS_HEIGHT = 700
SECTION_ICON_SIZE = 20


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


class SettingsDialog(Adw.Dialog):
    """Settings window as in Qt: a list of sections, the section page, a status line."""

    __gtype_name__ = "TengaSettingsDialog"

    __gsignals__ = {
        "settings-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, config, context=None) -> None:
        super().__init__()
        self.set_title("Настройки")
        self.set_content_width(SETTINGS_WIDTH)
        self.set_content_height(SETTINGS_HEIGHT)
        # Без минимума libadwaita предупреждает и не знает, когда ужимать окно
        # настроек в узкий режим; 360×294 — минимум из документации Adw.Dialog.
        self.set_size_request(360, 294)
        self._pages: dict[str, Adw.PreferencesPage] = {}
        # Итог последней записи от приложения: None — никто не ответил (тесты).
        self._persisted: bool | None = None
        self._config = config
        self._context = context
        self._fetch_releases = fetch_releases
        self._core_update_thread = None
        # None — проверка прав для TUN ещё не запускалась.
        self._tun_problems: list[str] | None = None

        self._build_general_page()
        self._build_monitoring_page()
        self._build_dns_page()
        self._build_routing_page()
        self._build_bypass_page()
        self._build_subscriptions_page()
        self._build_about_page()
        self._build_layout()

        self._loading = False
        self._load()
        self._autosave_source = 0
        seen = set()
        for value in vars(self).values():
            if isinstance(value, KeyedCombo):
                value = value.row
            if id(value) in seen:
                continue
            seen.add(id(value))
            if isinstance(value, Adw.EntryRow):
                value.connect("changed", self._queue_save)
            elif isinstance(value, Adw.SwitchRow):
                value.connect("notify::active", self._queue_save)
            elif isinstance(value, Adw.SpinRow):
                value.connect("notify::value", self._queue_save)
            elif isinstance(value, Adw.ComboRow):
                value.connect("notify::selected", self._queue_save)
        self.routing.connect_changed(self._queue_save)
        self.connect("closed", self._flush_save)

    def _add_page(self, key: str, page: Adw.PreferencesPage) -> None:
        self._pages[key] = page

    def _build_layout(self) -> None:
        """Section list on the left, the page with its title on the right, status below."""
        self._sections = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._sections.add_css_class("navigation-sidebar")
        self._sections.add_css_class("settings-sidebar")
        self._section_keys: list[str] = []
        self._section_icons: list[str] = []
        for key, title, icon in SETTINGS_SECTIONS:
            path = str(get_asset_path(f"icons/ui/{icon}.svg"))
            line = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6)
            image = Gtk.Image.new_from_file(path)
            image.set_pixel_size(SECTION_ICON_SIZE)
            image.add_css_class("settings-icon")
            line.append(image)
            line.append(Gtk.Label(label=title, xalign=0.0))
            self._sections.append(line)
            self._section_keys.append(key)
            self._section_icons.append(path)
        self._sections.connect("row-selected", self._on_section_selected)

        sidebar_view = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar(show_end_title_buttons=False)
        sidebar_header.set_title_widget(Adw.WindowTitle(title="Настройки"))
        sidebar_view.add_top_bar(sidebar_header)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self._sections)
        sidebar_view.set_content(scroll)
        sidebar = Adw.NavigationPage(title="Настройки", child=sidebar_view)

        self._stack = Gtk.Stack(vexpand=True)
        for key, page in self._pages.items():
            self._stack.add_named(page, key)
        self._section_title = Adw.WindowTitle(title=SETTINGS_SECTIONS[0][1])
        content_view = Adw.ToolbarView()
        content_header = Adw.HeaderBar()
        content_header.set_title_widget(self._section_title)
        content_view.add_top_bar(content_header)
        content_view.set_content(self._stack)

        footer = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=16, margin_end=16)
        self._status = Gtk.Label(label=SAVE_IDLE, xalign=0.0, hexpand=True, wrap=True)
        self._status.add_css_class("dim-label")
        footer.append(self._status)
        self.close_button = Gtk.Button(label="Закрыть")
        self.close_button.connect("clicked", lambda _b: self.close())
        footer.append(self.close_button)
        content_view.add_bottom_bar(footer)
        self._content_page = Adw.NavigationPage(title=SETTINGS_SECTIONS[0][1], child=content_view)

        self._split = Adw.NavigationSplitView(
            sidebar=sidebar,
            content=self._content_page,
            min_sidebar_width=200,
            max_sidebar_width=240,
            sidebar_width_fraction=0.24,
        )
        self.set_child(self._split)

        # Узкий диалог (окно меньше 640 по ширине): список разделов и страница
        # по очереди, как в любом диалоге libadwaita.
        narrow = Adw.Breakpoint.new(
            Adw.BreakpointCondition.new_length(
                Adw.BreakpointConditionLengthType.MAX_WIDTH, 600, Adw.LengthUnit.SP
            )
        )
        narrow.add_setter(self._split, "collapsed", True)
        self.add_breakpoint(narrow)

        self._sections.select_row(self._sections.get_row_at_index(0))

    def _on_section_selected(self, _list, row) -> None:
        if row is None:
            return
        index = row.get_index()
        key = self._section_keys[index]
        title = SETTINGS_SECTIONS[index][1]
        self._stack.set_visible_child_name(key)
        self._section_title.set_title(title)
        self._content_page.set_title(title)
        self._split.set_show_content(True)

    def select_section(self, key: str) -> None:
        """Open the section with the given key (`SETTINGS_SECTIONS`)."""
        row = self._sections.get_row_at_index(self._section_keys.index(key))
        self._sections.select_row(row)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status.set_text(text)
        if error:
            self._status.remove_css_class("dim-label")
            self._status.add_css_class("error")
        else:
            self._status.remove_css_class("error")
            self._status.add_css_class("dim-label")

    def set_save_result(self, saved: bool, *, reconnect: bool | None = None) -> None:
        """The application reports whether the settings reached the disk."""
        self._persisted = saved
        if reconnect is None:
            reconnect = self._needs_reconnect()
        self._set_status(save_status_text(saved=saved, reconnect=reconnect), error=not saved)

    def _needs_reconnect(self) -> bool:
        if getattr(self._context, "proxy_state", None) is None:
            return False
        from src.ui.logic.settings_state import pending_settings

        return bool(pending_settings(self._context))

    def _queue_save(self, *_args) -> None:
        if self._loading:
            return
        self._set_status(SAVE_PENDING)
        if self._autosave_source:
            GLib.source_remove(self._autosave_source)
        self._autosave_source = GLib.timeout_add(500, self._autosave)

    def _autosave(self) -> bool:
        self._autosave_source = 0
        self.save()
        return GLib.SOURCE_REMOVE

    def _flush_save(self, *_args) -> None:
        if self._autosave_source:
            GLib.source_remove(self._autosave_source)
            self._autosave_source = 0
            self.save()

    # --- страницы ---

    def _build_general_page(self) -> None:
        page = Adw.PreferencesPage(title="Общие", icon_name="preferences-system-symbolic")
        self._general_page = page
        self._add_page("general", page)

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

        self.kill_switch_row = Adw.SwitchRow(title=KILL_SWITCH_LABEL, subtitle=KILL_SWITCH_HINT)
        self.kill_switch_row.set_visible(kill_switch_available())
        runtime.add(self.kill_switch_row)

        self.tun_access_row = Adw.ActionRow(title="TUN не заработает")
        self.tun_access_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        self.tun_access_row.add_css_class("warning")
        # В подписи — команда для исправления: её копируют в терминал.
        self.tun_access_row.set_subtitle_selectable(True)
        self.tun_access_row.set_visible(False)
        runtime.add(self.tun_access_row)

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

        appearance = Adw.PreferencesGroup(title="Окно")
        page.add(appearance)

        self._theme = KeyedCombo("Тема", THEMES, THEME_LABELS)
        self.theme_row = self._theme.row
        # Тема меняется сразу, чтобы выбор было видно, а в настройки
        # попадает при закрытии диалога, как и остальные поля.
        self.theme_row.connect("notify::selected", lambda *_: apply_theme(self._theme.selected()))
        appearance.add(self.theme_row)

        self.close_to_tray_row = Adw.SwitchRow(
            title="Сворачивать в трей при закрытии окна",
            subtitle="Без трея закрытие окна всегда завершает приложение",
        )
        appearance.add(self.close_to_tray_row)

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
        self._add_page("monitoring", page)

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

        failover = Adw.PreferencesGroup(
            title="Автопереключение",
            description=("Если сервер перестал отвечать, подключается другой сервер той же группы"),
        )
        page.add(failover)

        self.failover_row = Adw.SwitchRow(title="Переключаться автоматически")
        self.failover_row.connect("notify::active", lambda *_: self._sync_monitoring())
        failover.add(self.failover_row)

        self.failover_threshold_row = Adw.SpinRow.new_with_range(1, 10, 1)
        self.failover_threshold_row.set_title("Порог")
        self.failover_threshold_row.set_subtitle("Неудачных проверок подряд")
        failover.add(self.failover_threshold_row)

    def refresh_subscriptions(self) -> None:
        """Reload the subscription list from the store; the window calls it on changes."""
        store = getattr(self._context, "profiles", None)
        if store is None:
            return
        groups = store.groups
        counts = {gid: len(store.get_profiles_in_group(gid)) for gid in groups}
        self.subscriptions_list.set_data(groups, counts)

    def show_dns_page(self) -> None:
        self.select_section("dns")

    def _build_dns_page(self) -> None:
        page = Adw.PreferencesPage(title="DNS", icon_name="network-server-symbolic")
        self._dns_page = page
        self._add_page("dns", page)

        group = Adw.PreferencesGroup(title="Провайдер")
        page.add(group)

        self._dns = KeyedCombo("DNS-сервер", DnsProvider.ALL, DnsProvider.LABELS)
        self.dns_row = self._dns.row
        group.add(self.dns_row)

        custom = Adw.PreferencesGroup(
            title="Свой адрес",
            description="Непустое поле перекрывает выбранного провайдера. "
            "Примеры: 8.8.8.8, https://dns.google/dns-query",
        )
        page.add(custom)

        self.dns_url_row = Adw.EntryRow(title="Адрес DNS")
        custom.add(self.dns_url_row)
        self.dns_additional_row = Adw.EntryRow(title="Дополнительный DNS")
        custom.add(self.dns_additional_row)

        options = Adw.PreferencesGroup(title="Опции")
        page.add(options)

        self.dns_proxy_row = Adw.SwitchRow(
            title="Запросы через прокси",
            subtitle="Помогает обойти блокировки на уровне DNS",
        )
        options.add(self.dns_proxy_row)

        self.dns_intercept_row = Adw.SwitchRow(
            title="Перехватывать DNS приложений",
            subtitle="Режим TUN: запросы приложений обрабатывает ядро — "
            "действуют списки маршрутизации и блокировка",
        )
        options.add(self.dns_intercept_row)

    def _build_routing_page(self) -> None:
        from src.ui.logic.routing_form import GLOBAL_PAGE_HINT, VPN_LIST_HINT
        from src.ui.widgets.routing_form import RoutingForm

        page = Adw.PreferencesPage(
            title=platform_texts.settings_page_title("routing"),
            icon_name="network-workgroup-symbolic",
            description=GLOBAL_PAGE_HINT,
        )
        self.routing_page = page
        self._add_page("routing", page)

        self.routing = RoutingForm(page, vpn_hint=VPN_LIST_HINT)

        extra = self.routing_extra_group = Adw.PreferencesGroup(title="Дополнительно")
        extra.set_visible(getattr(self._config, "routing_backup", None) is not None)
        page.add(extra)
        # Без подтверждения, как в Android: откат меняет только списки,
        # которые пользователь сам только что заменил импортом.
        self.restore_routing_row = Adw.ActionRow(
            title="Маршрутизация до импорта",
            subtitle="Вернёт режим и списки, которые были до последнего импорта",
        )
        self.restore_routing_button = Gtk.Button(
            label="Вернуть", valign=Gtk.Align.CENTER, action_name="app.restore-routing"
        )
        self.restore_routing_row.add_suffix(self.restore_routing_button)
        self.restore_routing_row.set_visible(
            getattr(self._config, "routing_backup", None) is not None
        )
        extra.add(self.restore_routing_row)

    def _shared_routing(self):
        from pathlib import Path

        from src.ui.logic.routing_import import effective_routing

        config_dir = getattr(self._context, "config_dir", None) if self._context else None
        return effective_routing(self._config.routing, Path(config_dir) if config_dir else None)

    def _load_routing(self) -> None:
        self._loading = True
        try:
            self.routing.load(self._shared_routing())
        finally:
            self._loading = False
        # Что показано после загрузки: без правок форма общие правила не пишет,
        # и старая установка продолжает читать списки из своих файлов.
        self._routing_loaded = self.routing.values()

    def sync_restore_routing(self, available: bool) -> None:
        """Импорт или откат поменял общие правила, пока открыты настройки."""
        self.routing_extra_group.set_visible(available)
        self.restore_routing_row.set_visible(available)
        self._load_routing()

    def _build_bypass_page(self) -> None:
        page = Adw.PreferencesPage(
            title=platform_texts.settings_page_title("bypass"),
            icon_name="security-high-symbolic",
        )
        self._add_page("bypass", page)

        fragment = Adw.PreferencesGroup(
            title="Фрагментация TLS",
            description="Делит начало TLS-соединения на части, чтобы фильтр не разобрал "
            "имя сервера. Действует на серверы с TLS и Reality. Вступает в силу после переподключения.",
        )
        page.add(fragment)

        self.fragment_row = Adw.SwitchRow(title="Включить фрагментацию")
        self.fragment_row.connect("notify::active", lambda *_: self._sync_fragment())
        fragment.add(self.fragment_row)

        self.fragment_packets_row = Adw.EntryRow(title="Пакеты: tlshello или номера, 1-3")
        fragment.add(self.fragment_packets_row)

        self.fragment_length_row = Adw.EntryRow(title="Размер фрагмента, байт: 100-200")
        fragment.add(self.fragment_length_row)

        self.fragment_delay_row = Adw.EntryRow(title="Пауза между фрагментами, мс: 10-20")
        fragment.add(self.fragment_delay_row)

        mux = Adw.PreferencesGroup(title="Мультиплексирование")
        page.add(mux)

        self.mux_row = Adw.SwitchRow(
            title="Включить mux",
            subtitle="Несколько потоков в одном соединении. Только VLESS и Trojan, "
            "кроме XHTTP и Vision",
        )
        mux.add(self.mux_row)

    def _build_subscriptions_page(self) -> None:
        page = Adw.PreferencesPage(
            title=platform_texts.settings_page_title("subscriptions"),
            icon_name="folder-download-symbolic",
        )
        self._add_page("subscriptions", page)

        from src.ui.widgets.subscriptions_list import SubscriptionsList

        self.subscriptions_list = SubscriptionsList()
        page.add(self.subscriptions_list)
        self.subscription_buttons = self.subscriptions_list.buttons
        self.refresh_subscriptions()

        request = Adw.PreferencesGroup(
            title="Запрос к провайдеру",
            description=f"Пустое поле — {DEFAULT_USER_AGENT}: так представляется большинство "
            "клиентов, и провайдеры отдают ему обычный список серверов.",
        )
        page.add(request)

        self.user_agent_row = Adw.EntryRow(title="User-Agent")
        request.add(self.user_agent_row)

        self.device_info_row = Adw.SwitchRow(
            title="Отправлять данные устройства",
            subtitle="Идентификатор, система и модель. Нужны провайдерам, "
            "которые считают лимит устройств",
        )
        request.add(self.device_info_row)
        self.sub_exceptions_row = Adw.EntryRow(title="Разрешённые HTTP/LAN URL (через пробел)")
        request.add(self.sub_exceptions_row)
        self.sub_insecure_row = Adw.SwitchRow(
            title="Не проверять TLS-сертификат подписок",
            subtitle="Отдельное исключение; не разрешает доступ к HTTP или локальной сети",
        )
        request.add(self.sub_insecure_row)

    def _build_about_page(self) -> None:
        page = Adw.PreferencesPage(
            title=platform_texts.settings_page_title("about"),
            icon_name="help-about-symbolic",
        )
        self._add_page("about", page)

        group = Adw.PreferencesGroup(title="Veblock")
        page.add(group)

        group.add(self._value_row("Версия", app_version()))
        self.app_update_row = Adw.ActionRow(title="Обновление приложения")
        self.app_check_button = Gtk.Button(label="Проверить", valign=Gtk.Align.CENTER)
        self.app_check_button.connect("clicked", self._check_app_update)
        self.app_update_row.add_suffix(self.app_check_button)
        self.app_release_button = Gtk.Button(label="Открыть релиз", valign=Gtk.Align.CENTER)
        self.app_release_button.connect("clicked", self._open_app_release)
        self.app_update_row.add_suffix(self.app_release_button)
        group.add(self.app_update_row)
        self.app_update_row.set_subtitle(
            self._config.app_update_target or "Нет сведений о новой версии"
        )
        self.app_release_button.set_sensitive(bool(self._config.app_update_url))
        updates = Adw.PreferencesGroup(title="Настройки обновлений")
        page.add(updates)
        self.app_updates_row = Adw.SwitchRow(title="Проверять обновления приложения раз в сутки")
        self.app_updates_row.set_active(self._config.app_update_enabled)
        updates.add(self.app_updates_row)
        self.app_prereleases_row = Adw.SwitchRow(
            title="Предлагать предварительные версии приложения"
        )
        self.app_prereleases_row.set_active(self._config.app_update_prerelease)
        updates.add(self.app_prereleases_row)
        self.core_updates_row = Adw.SwitchRow(title="Проверять обновления ядра раз в три дня")
        self.core_updates_row.set_active(self._config.core_update_enabled)
        updates.add(self.core_updates_row)
        manager = getattr(self._context, "xray_manager", None) if self._context else None
        self._core_version = core_version(manager)
        group.add(self._value_row("Ядро xray", self._core_version))

        self.core_update_row = Adw.ActionRow(title="Обновление ядра")
        self.core_update_button = Gtk.Button(label="Проверить", valign=Gtk.Align.CENTER)
        self.core_update_button.connect("clicked", lambda _button: self.check_core_update())
        self.core_update_button.set_sensitive(self._context is not None)
        self.core_update_row.add_suffix(self.core_update_button)
        group.add(self.core_update_row)
        self._show_core_update()

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

        self.geo_row = Adw.ActionRow(title="Геобазы")
        self.geo_row.set_use_markup(False)
        self.geo_row.set_subtitle(geo_summary(current_catalog()))
        self.geo_update_button = Gtk.Button(label="Обновить", valign=Gtk.Align.CENTER)
        self.geo_update_button.connect("clicked", self._on_update_geo)
        self.geo_row.add_suffix(self.geo_update_button)
        actions.add(self.geo_row)

    @staticmethod
    def _value_row(title: str, value: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=value)
        # Выделять есть смысл настоящее значение — его копируют в отчёт об
        # ошибке. Копировать прочерк незачем: строка только запутывала бы.
        row.set_subtitle_selectable(value != UNKNOWN)
        return row

    # --- состояние ---

    def _sync_mode(self) -> None:
        # Поля TUN прячутся, а не гаснут, как в Qt; значения в них остаются.
        tun = self._mode.selected() == ProxyMode.TUN
        self.tun_name_row.set_visible(tun)
        self.tun_mtu_row.set_visible(tun)
        self.kill_switch_row.set_visible(tun and kill_switch_available())
        if tun and self._tun_problems is None:
            self._check_tun_access()
        self._sync_tun_access()

    def _check_tun_access(self) -> None:
        # sudo и SCM отвечают не мгновенно: открытие настроек ждать не должно.
        from src.core.config import find_xray_binary

        self._tun_problems = []
        run_in_background(
            lambda: tun_access.tun_problems(find_xray_binary()),
            on_done=self._on_tun_access_checked,
            name="tenga-tun-access",
        )

    def _on_tun_access_checked(self, problems: list[str]) -> None:
        self._tun_problems = list(problems)
        self._sync_tun_access()

    def _sync_tun_access(self) -> None:
        problems = self._tun_problems or []
        self.tun_access_row.set_subtitle("\n".join(problems))
        self.tun_access_row.set_visible(self._mode.selected() == ProxyMode.TUN and bool(problems))

    def _sync_monitoring(self) -> None:
        monitoring = self.monitoring_row.get_active()
        self.interval_row.set_sensitive(monitoring)
        # Без мониторинга проверок нет — переключаться не по чему.
        self.failover_row.set_sensitive(monitoring)
        self.failover_threshold_row.set_sensitive(monitoring and self.failover_row.get_active())

    def _sync_fragment(self) -> None:
        active = self.fragment_row.get_active()
        self.fragment_packets_row.set_sensitive(active)
        self.fragment_length_row.set_sensitive(active)
        self.fragment_delay_row.set_sensitive(active)

    def _load(self) -> None:
        config = self._config

        self.address_row.set_text(config.inbound_address)
        self.port_row.set_value(float(config.inbound_socks_port))

        self._mode.select(getattr(config, "proxy_mode", ProxyMode.TUN))
        self.tun_name_row.set_text(getattr(config, "tun_name", DEFAULT_TUN_NAME))
        self.tun_mtu_row.set_value(float(getattr(config, "tun_mtu", 1500)))
        self.kill_switch_row.set_active(bool(getattr(config, "tun_kill_switch", False)))
        self._sync_mode()

        self._log_level.select(getattr(config, "log_level", DEFAULT_LOG_LEVEL))
        self._theme.select(normalize_theme(getattr(config, "theme", None)))
        self.close_to_tray_row.set_active(bool(getattr(config, "close_to_tray", True)))

        monitoring = config.monitoring
        self.monitoring_row.set_active(monitoring.enabled)
        self.interval_row.set_value(float(monitoring.check_interval_seconds))
        self.failover_row.set_active(monitoring.failover_enabled)
        self.failover_threshold_row.set_value(float(monitoring.failover_threshold))
        self._sync_monitoring()

        dns = config.dns
        self._dns.select(dns.provider)
        self.dns_url_row.set_text(dns.custom_url)
        self.dns_additional_row.set_text(dns.additional_url)
        self.dns_proxy_row.set_active(dns.use_proxy)
        self.dns_intercept_row.set_active(getattr(dns, "intercept", True))

        fragment = config.tls_fragment
        self.fragment_row.set_active(fragment.enabled)
        self.fragment_packets_row.set_text(fragment.packets)
        self.fragment_length_row.set_text(fragment.length)
        self.fragment_delay_row.set_text(fragment.delay)
        self._sync_fragment()
        self.mux_row.set_active(config.mux_default_on)

        user_agent = config.user_agent.strip()
        self.user_agent_row.set_text("" if user_agent == LEGACY_USER_AGENT else user_agent)
        self.device_info_row.set_active(config.sub_send_device_info)
        self.sub_exceptions_row.set_text(" ".join(config.sub_source_exceptions))
        self.sub_insecure_row.set_active(config.sub_insecure)

        self._load_routing()

    def save(self) -> bool:
        """Write the form back into the configuration object."""
        config = copy.deepcopy(self._config)

        config.inbound_address = self.address_row.get_text().strip()
        config.inbound_socks_port = int(self.port_row.get_value())

        config.proxy_mode = self._mode.selected()
        # An empty/invalid interface name is reported before committing.
        config.tun_name = self.tun_name_row.get_text().strip()
        config.tun_mtu = int(self.tun_mtu_row.get_value())
        config.tun_kill_switch = self.kill_switch_row.get_active()

        config.log_level = self._log_level.selected()
        config.theme = self._theme.selected()
        config.close_to_tray = self.close_to_tray_row.get_active()

        config.monitoring.enabled = self.monitoring_row.get_active()
        config.monitoring.check_interval_seconds = int(self.interval_row.get_value())
        config.monitoring.failover_enabled = self.failover_row.get_active()
        config.monitoring.failover_threshold = int(self.failover_threshold_row.get_value())

        config.dns.provider = self._dns.selected()
        config.dns.custom_url = self.dns_url_row.get_text().strip()
        config.dns.additional_url = self.dns_additional_row.get_text().strip()
        config.dns.use_proxy = self.dns_proxy_row.get_active()
        config.dns.intercept = self.dns_intercept_row.get_active()

        # Validate the candidate before changing any live configuration field.
        config.tls_fragment = TlsFragmentSettings(
            enabled=self.fragment_row.get_active(),
            packets=self.fragment_packets_row.get_text(),
            length=self.fragment_length_row.get_text(),
            delay=self.fragment_delay_row.get_text(),
        )
        config.mux_default_on = self.mux_row.get_active()

        config.app_update_enabled = self.app_updates_row.get_active()
        config.app_update_prerelease = self.app_prereleases_row.get_active()
        config.core_update_enabled = self.core_updates_row.get_active()
        config.user_agent = self.user_agent_row.get_text().strip()
        config.sub_source_exceptions = self.sub_exceptions_row.get_text().split()
        config.sub_insecure = self.sub_insecure_row.get_active()
        config.sub_send_device_info = self.device_info_row.get_active()
        if config.sub_send_device_info:
            # Идентификатор сохранится вместе с настройками при закрытии диалога.
            ensure_hwid(config)

        if self.routing.values() != self._routing_loaded:
            from src.ui.logic.routing_import import store_shared_routing

            routing = copy.deepcopy(config.routing)
            try:
                self.routing.read(routing)
            except ValueError as error:
                self._set_status(invalid_text(str(error)), error=True)
                return False
            store_shared_routing(config, routing)

        errors = validate_settings(config)
        self.validation_errors = errors
        for name in (
            "address",
            "tun_name",
            "dns_url",
            "dns_additional",
            "fragment_packets",
            "fragment_length",
            "fragment_delay",
            "sub_exceptions",
        ):
            row = getattr(self, name + "_row")
            if name in errors:
                row.add_css_class("error")
                row.set_tooltip_text(errors[name])
            else:
                row.remove_css_class("error")
                row.set_tooltip_text(None)
        if errors:
            self._set_status(invalid_text(next(iter(errors.values()))), error=True)
            return False
        self._config.__dict__.update(config.__dict__)
        self._routing_loaded = self.routing.values()
        # Приложение пишет настройки на диск и отвечает `set_save_result`;
        # без ответа (диалог без приложения) запись считается успешной.
        self._persisted = None
        self.emit("settings-saved")
        if self._persisted is None:
            self.set_save_result(True)
        return self._persisted is not False

    # --- вспомогательное для тестов и внешнего кода ---

    def selected_mode(self) -> str:
        return self._mode.selected()

    def select_mode(self, key: str) -> None:
        self._mode.select(key)
        self._sync_mode()

    def select_dns(self, key: str) -> None:
        self._dns.select(key)

    def selected_theme(self) -> str:
        return self._theme.selected()

    def select_theme(self, key: str) -> None:
        self._theme.select(key)

    def select_log_level(self, key: str) -> None:
        self._log_level.select(key)

    def _open_app_release(self, *_args) -> None:
        from src.core.app_update import safe_release_url

        url = self._config.app_update_url
        if safe_release_url(url):
            Gio.AppInfo.launch_default_for_uri(url, None)

    def _check_app_update(self, *_args) -> None:
        from src.core.app_update import check_app_update, fetch_app_releases
        from src.sub.route import local_proxy_url

        self.app_check_button.set_sensitive(False)
        self.app_update_row.set_subtitle("Проверка…")

        def work():
            proxy = (
                (lambda: local_proxy_url(self._config, self._context.proxy_state))
                if self._context
                else None
            )
            return check_app_update(
                self._config, app_version(), force=True, fetch=lambda: fetch_app_releases(proxy)
            )

        def done(release):
            self.app_check_button.set_sensitive(True)
            text = f"Доступна версия {release.version}" if release else "Новых версий нет"
            if release and not release.has_asset:
                text += "; " + platform_texts.missing_release_asset()
            self.app_update_row.set_subtitle(text)
            self.app_release_button.set_sensitive(bool(release))
            if self._context:
                self._context.save_config()

        def failed(_error):
            self.app_check_button.set_sensitive(True)
            self.app_update_row.set_subtitle("Не удалось проверить обновления")
            if self._context:
                self._context.save_config()

        run_in_background(work, on_done=done, on_error=failed, name="tenga-app-update-manual")

    def _on_update_geo(self, _button: Gtk.Button) -> None:
        # Скачивание — десятки мегабайт: в главном потоке окно бы замерло.
        self.geo_update_button.set_sensitive(False)
        self.geo_row.set_subtitle("Скачивание…")
        run_in_background(
            lambda: update_geo_bases(USER_GEO_DIR),
            on_done=self._on_geo_updated,
            on_error=self._on_geo_update_failed,
            name="tenga-geo-update",
        )

    def _on_geo_updated(self, catalog) -> None:
        self.geo_update_button.set_sensitive(True)
        self.geo_row.set_subtitle(f"{geo_summary(catalog)} — применятся после переподключения")
        if self._context is not None:
            self._context.proxy_state.notify_listeners()

    def _on_geo_update_failed(self, error: BaseException) -> None:
        self.geo_update_button.set_sensitive(True)
        self.geo_row.set_subtitle(f"Не обновлены: {error}")

    # --- обновление ядра ---

    def _show_core_update(self) -> None:
        status = evaluate(self._core_version, known_releases(self._config))
        self.core_update_row.set_subtitle(core_update_text(status))

    def set_release_fetcher(self, fetch) -> None:
        """Replace the function asking GitHub about releases (tests)."""
        self._fetch_releases = fetch

    def check_core_update(self) -> None:
        """Ask for the releases in the background and redraw the row."""
        if self._context is None:
            return

        self.core_update_button.set_sensitive(False)
        self.core_update_row.set_subtitle("Проверяю…")
        self._core_update_thread = run_in_background(
            lambda: refresh_known_releases(
                self._config, now=time.time(), fetch=self._fetch_releases
            ),
            on_done=self._on_core_update_checked,
            on_error=self._on_core_update_failed,
            name="tenga-core-update",
        )

    def _on_core_update_checked(self, _releases) -> None:
        self.core_update_button.set_sensitive(True)
        self._show_core_update()
        # Время проверки хранится в настройках: иначе при следующем запуске
        # приложение спросило бы GitHub снова.
        self._context.save_config()

    def _on_core_update_failed(self, _error: BaseException) -> None:
        self.core_update_button.set_sensitive(True)
        self.core_update_row.set_subtitle("Не удалось проверить обновления")

    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
        if self._core_update_thread is not None:
            self._core_update_thread.join(timeout)

        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def _on_clear_logs(self, _button: Gtk.Button) -> None:
        if self._context is None:
            return
        from src.ui.dialogs.confirm import build_delete_confirmation

        def clear():
            def done(result):
                self.clear_logs_row.set_subtitle(f"Очищено файлов: {result[0]}")

            run_in_background(self._context.log_manager.clear_all_logs, on_done=done)

        dialog = build_delete_confirmation(
            "Очистить журналы?",
            "Все сохранённые записи будут удалены.",
            clear,
            confirm_label="Очистить",
        )
        dialog.present(self)

    # --- окно разделов: аксессоры для тестов ---

    def section_titles_for_test(self) -> list[str]:
        return [title for _key, title, _icon in SETTINGS_SECTIONS]

    def section_icon_for_test(self, index: int) -> str:
        return self._section_icons[index]

    def get_section_title(self) -> str:
        return self._section_title.get_title()

    def get_visible_page(self) -> Adw.PreferencesPage:
        return self._stack.get_visible_child()

    def get_status_text(self) -> str:
        return self._status.get_text()

    @staticmethod
    def group_titles_for_test(page: Adw.PreferencesPage) -> list[str]:
        titles = []
        stack = [page]
        while stack:
            widget = stack.pop(0)
            if isinstance(widget, Adw.PreferencesGroup):
                titles.append(widget.get_title())
                continue
            child = widget.get_first_child()
            children = []
            while child is not None:
                children.append(child)
                child = child.get_next_sibling()
            stack[0:0] = children
        return titles
