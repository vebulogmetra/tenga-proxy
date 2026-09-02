"""Per-profile VPN and routing settings (GTK4)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.ui.dialogs4.settings import KeyedCombo
from src.ui.logic.forms import parse_host_list

ORDER_PRESETS: dict[str, list[str]] = {
    "direct_vpn_proxy": ["direct", "vpn", "proxy"],
    "direct_proxy_vpn": ["direct", "proxy", "vpn"],
    "vpn_direct_proxy": ["vpn", "direct", "proxy"],
    "vpn_proxy_direct": ["vpn", "proxy", "direct"],
    "proxy_direct_vpn": ["proxy", "direct", "vpn"],
    "proxy_vpn_direct": ["proxy", "vpn", "direct"],
}

ORDER_LABELS = {
    "direct_vpn_proxy": "Напрямую → VPN → Прокси",
    "direct_proxy_vpn": "Напрямую → Прокси → VPN",
    "vpn_direct_proxy": "VPN → Напрямую → Прокси",
    "vpn_proxy_direct": "VPN → Прокси → Напрямую",
    "proxy_direct_vpn": "Прокси → Напрямую → VPN",
    "proxy_vpn_direct": "Прокси → VPN → Напрямую",
}

LIST_HINT = "По одному домену или подсети в строке"


def _list_view(title: str, subtitle: str) -> tuple[Adw.PreferencesGroup, Gtk.TextView]:
    """Build a titled text area for one routing list."""
    group = Adw.PreferencesGroup(title=title, description=subtitle)

    view = Gtk.TextView()
    view.set_monospace(True)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.set_left_margin(8)
    view.set_right_margin(8)

    scrolled = Gtk.ScrolledWindow(min_content_height=120)
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_child(view)
    scrolled.add_css_class("card")

    group.add(scrolled)
    return group, view


def _read(view: Gtk.TextView) -> str:
    buffer = view.get_buffer()
    start, end = buffer.get_bounds()
    return buffer.get_text(start, end, True)


class ProfileRoutingDialog(Adw.PreferencesDialog):
    """VPN link and routing rules of one profile."""

    __gtype_name__ = "TengaProfileRoutingDialog"

    __gsignals__ = {
        "routing-saved": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, profile) -> None:
        super().__init__()
        self.set_title("VPN и маршруты")
        self._profile = profile

        self._build_vpn_page()
        self._build_routing_page()

        self._load()

    # --- страницы ---

    def _build_vpn_page(self) -> None:
        page = Adw.PreferencesPage(title="VPN", icon_name="network-vpn-symbolic")
        self.add(page)

        # Профиль и VPN на одной странице: две строки не оправдывают отдельной
        # вкладки, а имя всё равно правится в диалоге редактирования профиля.
        profile_group = Adw.PreferencesGroup(title="Профиль")
        page.add(profile_group)

        self.name_row = Adw.EntryRow(title="Имя")
        profile_group.add(self.name_row)

        self.address_row = Adw.ActionRow(title="Сервер")
        self.address_row.set_subtitle_selectable(True)
        profile_group.add(self.address_row)

        group = Adw.PreferencesGroup(
            title="Подключение NetworkManager",
            description="Профиль может поднимать VPN перед запуском прокси",
        )
        page.add(group)

        self.vpn_row = Adw.SwitchRow(title="Использовать VPN")
        self.vpn_row.connect("notify::active", lambda *_: self._sync_vpn())
        group.add(self.vpn_row)

        self.vpn_name_row = Adw.EntryRow(title="Имя подключения")
        group.add(self.vpn_name_row)

        self.vpn_auto_row = Adw.SwitchRow(
            title="Подключать автоматически",
            subtitle="Поднимать VPN при запуске профиля и опускать при остановке",
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
        page = Adw.PreferencesPage(title="Маршрутизация", icon_name="network-workgroup-symbolic")
        self.add(page)

        mode_group = Adw.PreferencesGroup(title="Режим")
        page.add(mode_group)

        self._mode = KeyedCombo("Правила", RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_row = self._mode.row
        self.mode_row.connect("notify::selected", lambda *_: self._sync_mode())
        mode_group.add(self.mode_row)

        self._order = KeyedCombo("Приоритет групп", list(ORDER_PRESETS.keys()), ORDER_LABELS)
        self.order_row = self._order.row
        mode_group.add(self.order_row)

        self.bypass_row = Adw.SwitchRow(
            title="Локальные сети напрямую",
            subtitle="127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие",
        )
        mode_group.add(self.bypass_row)

        self.proxy_group, self.proxy_view = _list_view("Через прокси", LIST_HINT)
        page.add(self.proxy_group)

        self.direct_group, self.direct_view = _list_view("Напрямую", LIST_HINT)
        page.add(self.direct_group)

        self.vpn_group, self.vpn_view = _list_view("Через VPN", LIST_HINT)
        page.add(self.vpn_group)

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

    def _sync_mode(self) -> None:
        # В режиме «весь трафик через прокси» списки не применяются вовсе:
        # оставлять их активными — обещать пользователю несуществующий эффект.
        custom = self._mode.selected() == RoutingMode.CUSTOM
        for widget in (
            self.proxy_view,
            self.direct_view,
            self.vpn_view,
            self.order_row,
            self.bypass_row,
        ):
            widget.set_sensitive(custom)

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

        routing = getattr(profile, "routing_settings", None) or RoutingSettings()
        self._mode.select(routing.mode)
        self.bypass_row.set_active(routing.bypass_local_networks)
        self.select_order(_current_order(routing))

        self.set_proxy_text("\n".join(routing.proxy_list or []))
        self.set_direct_text("\n".join(routing.direct_list or []))
        self.set_vpn_text("\n".join(routing.vpn_list or []))
        self._sync_mode()

    def save(self) -> None:
        """Write the form back into the profile."""
        profile = self._profile

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

        if getattr(profile, "routing_settings", None) is None:
            profile.routing_settings = RoutingSettings()
        routing = profile.routing_settings
        routing.mode = self._mode.selected()
        routing.bypass_local_networks = self.bypass_row.get_active()
        routing.rule_order = list(self.selected_order())
        routing.proxy_list = parse_host_list(self.proxy_text())
        routing.direct_list = parse_host_list(self.direct_text())
        routing.vpn_list = parse_host_list(self.vpn_text())

        self.emit("routing-saved")

    # --- доступ к полям ---

    def selected_mode(self) -> str:
        return self._mode.selected()

    def select_mode(self, key: str) -> None:
        self._mode.select(key)
        self._sync_mode()

    def selected_order(self) -> list[str]:
        return ORDER_PRESETS[self._order.selected()]

    def select_order(self, order: list[str]) -> None:
        for key, preset in ORDER_PRESETS.items():
            if preset == list(order):
                self._order.select(key)
                return
        # Порядок из другой версии или испорченный файл: берём первый пресет.
        self._order.select(next(iter(ORDER_PRESETS)))

    def proxy_text(self) -> str:
        return _read(self.proxy_view)

    def direct_text(self) -> str:
        return _read(self.direct_view)

    def vpn_text(self) -> str:
        return _read(self.vpn_view)

    def set_proxy_text(self, text: str) -> None:
        self.proxy_view.get_buffer().set_text(text)

    def set_direct_text(self, text: str) -> None:
        self.direct_view.get_buffer().set_text(text)

    def set_vpn_text(self, text: str) -> None:
        self.vpn_view.get_buffer().set_text(text)


def _current_order(routing) -> list[str]:
    try:
        return routing.get_rule_order()
    except AttributeError:
        return list(next(iter(ORDER_PRESETS.values())))
