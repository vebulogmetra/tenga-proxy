"""Per-profile VPN and routing settings (GTK4)."""

from __future__ import annotations

import copy

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, GObject, Gtk

from src.db.config import RoutingSettings, VpnSettings
from src.ui.dialogs.settings import KeyedCombo
from src.ui.logic import platform_texts


class ProfileRoutingDialog(Adw.PreferencesDialog):
    """VPN link and routing rules of one profile."""

    __gtype_name__ = "TengaProfileRoutingDialog"

    __gsignals__ = {
        "routing-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, profile, shared_routing: RoutingSettings) -> None:
        super().__init__()
        self.set_title("VPN и маршруты")
        self._profile = profile
        # Действующие общие правила: их показывает форма, пока своих нет.
        self._shared = shared_routing

        self._build_vpn_page()
        self._build_routing_page()

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
        self.form.connect_changed(self._queue_save)
        self.connect("closed", self._flush_save)

    def _queue_save(self, *_args) -> None:
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

    def _build_vpn_page(self) -> None:
        page = Adw.PreferencesPage(title="VPN", icon_name="network-vpn-symbolic")
        self.add(page)

        # Профиль и VPN на одной странице: две строки не оправдывают отдельной
        # вкладки, а имя всё равно правится в диалоге редактирования профиля.
        profile_group = Adw.PreferencesGroup(title="Сервер")
        page.add(profile_group)

        self.name_row = Adw.EntryRow(title="Имя")
        profile_group.add(self.name_row)

        self.address_row = Adw.ActionRow(title="Адрес")
        self.address_row.set_subtitle_selectable(True)
        profile_group.add(self.address_row)

        group = Adw.PreferencesGroup(
            title=platform_texts.vpn_group_title(),
            description=platform_texts.vpn_group_description(),
        )
        page.add(group)

        self.vpn_row = Adw.SwitchRow(title="Использовать VPN")
        self.vpn_row.connect("notify::active", lambda *_: self._sync_vpn())
        group.add(self.vpn_row)

        self.vpn_name_row = Adw.EntryRow(title="Имя подключения")
        group.add(self.vpn_name_row)

        self.vpn_auto_row = Adw.SwitchRow(
            title="Подключать автоматически",
            subtitle="Поднимать VPN при подключении к серверу и опускать при отключении",
        )
        group.add(self.vpn_auto_row)

        interfaces = Adw.PreferencesGroup(
            title="Интерфейсы",
            description="Пусто — определять автоматически",
        )
        page.add(interfaces)

        self.vpn_interface_row = Adw.EntryRow(title="Интерфейс VPN")
        interfaces.add(self.vpn_interface_row)

        self.direct_interface_row = Adw.EntryRow(title="Интерфейс прямого выхода")
        interfaces.add(self.direct_interface_row)

    def _build_routing_page(self) -> None:
        from src.ui.logic.routing_form import OWN_RULES_HINT, OWN_RULES_TITLE
        from src.ui.widgets.routing_form import RoutingForm

        page = Adw.PreferencesPage(title="Маршрутизация", icon_name="network-workgroup-symbolic")
        self.add(page)

        own = Adw.PreferencesGroup()
        page.add(own)
        self.own_rules_row = Adw.SwitchRow(title=OWN_RULES_TITLE, subtitle=OWN_RULES_HINT)
        self.own_rules_row.connect("notify::active", lambda *_: self._sync_own_rules())
        own.add(self.own_rules_row)

        self.form = RoutingForm(page)
        self.mode_row = self.form.mode_row
        self.order_row = self.form.order_row
        self.bypass_row = self.form.bypass_row
        self.ru_direct_row = self.form.ru_direct_row
        self.block_view = self.form.views["block"]
        self.proxy_view = self.form.views["proxy"]
        self.direct_view = self.form.views["direct"]
        self.vpn_view = self.form.views["vpn"]

    # --- состояние ---

    def _sync_vpn(self) -> None:
        enabled = self.vpn_row.get_active()
        for row in (
            self.vpn_name_row,
            self.vpn_auto_row,
            self.vpn_interface_row,
            self.direct_interface_row,
        ):
            row.set_sensitive(enabled)

    def _sync_own_rules(self) -> None:
        # Выключено — форма показывает общие правила только для чтения; текст
        # остаётся, пока открыт диалог, поэтому повторное включение ничего не теряет.
        self.form.set_enabled(self.own_rules_row.get_active())

    def _load(self) -> None:
        profile = self._profile
        bean = profile.bean

        self.name_row.set_text(bean.display_name)
        self.address_row.set_subtitle(f"{bean.server_address}:{bean.server_port}")

        vpn = getattr(profile, "vpn_settings", None) or VpnSettings()
        self.vpn_row.set_active(vpn.enabled)
        self.vpn_name_row.set_text(vpn.connection_name)
        self.vpn_auto_row.set_active(getattr(vpn, "auto_connect", False))
        self.vpn_interface_row.set_text(getattr(vpn, "interface_name", "") or "")
        self.direct_interface_row.set_text(getattr(vpn, "direct_interface", "") or "")
        self._sync_vpn()

        routing = getattr(profile, "routing_settings", None)
        self.own_rules_row.set_active(routing is not None)
        # Без своих правил форма показывает общие: включение начнётся с их копии.
        self.form.load(routing if routing is not None else self._shared)
        self._sync_own_rules()

    def save(self) -> bool:
        """Write the form back into the profile."""
        profile = self._profile
        routing = None
        if self.own_rules_row.get_active():
            routing = copy.deepcopy(getattr(profile, "routing_settings", None) or RoutingSettings())
            try:
                self.form.read(routing)
            except ValueError as error:
                self.set_title(str(error))
                return False
        self.set_title("VPN и маршруты")

        name = self.name_row.get_text().strip()
        if name:
            profile.bean.name = name

        if getattr(profile, "vpn_settings", None) is None:
            profile.vpn_settings = VpnSettings()
        vpn = profile.vpn_settings
        vpn.enabled = self.vpn_row.get_active()
        # Безымянное подключение NetworkManager не найдёт — сохраняем прежнее.
        connection_name = self.vpn_name_row.get_text().strip()
        if connection_name:
            vpn.connection_name = connection_name
        vpn.auto_connect = self.vpn_auto_row.get_active()
        vpn.interface_name = self.vpn_interface_row.get_text().strip()
        vpn.direct_interface = self.direct_interface_row.get_text().strip()

        # None — сервер использует общие правила из настроек приложения.
        profile.routing_settings = routing

        self.emit("routing-saved")
        return True

    # --- доступ к полям ---

    def selected_mode(self) -> str:
        return self.form.selected_mode()

    def select_mode(self, key: str) -> None:
        self.form.select_mode(key)

    def selected_order(self) -> list[str]:
        return self.form.selected_order()

    def select_order(self, order: list[str]) -> None:
        self.form.select_order(order)

    def block_text(self) -> str:
        return self.form.text("block")

    def proxy_text(self) -> str:
        return self.form.text("proxy")

    def direct_text(self) -> str:
        return self.form.text("direct")

    def vpn_text(self) -> str:
        return self.form.text("vpn")

    def set_block_text(self, text: str) -> None:
        self.form.set_text("block", text)

    def set_proxy_text(self, text: str) -> None:
        self.form.set_text("proxy", text)

    def set_direct_text(self, text: str) -> None:
        self.form.set_text("direct", text)

    def set_vpn_text(self, text: str) -> None:
        self.form.set_text("vpn", text)
