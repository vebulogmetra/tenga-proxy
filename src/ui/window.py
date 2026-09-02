"""Main application window (GTK4 + libadwaita)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from src.ui.logic.geometry import (
    MIN_HEIGHT,
    MIN_WIDTH,
    Geometry,
    format_geometry,
    parse_geometry,
)
from src.ui.logic.monitoring_view import monitoring_view
from src.ui.logic.status import ConnectionState, status_view
from src.ui.pages.monitoring import MonitoringPage
from src.ui.pages.profiles import ProfilesPage
from src.ui.pages.subscriptions import SubscriptionsPage
from src.ui.widgets.status_card import StatusCard

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.window")

NARROW_WIDTH = 550


class _EmptyStatus:
    """Stand-in used before the connection monitor exists."""

    proxy_ok = False
    vpn_ok = True
    last_check_time = 0.0
    proxy_error = ""
    vpn_error = ""


def load_css() -> None:
    """Attach the application stylesheet to the default display."""
    display = Gdk.Display.get_default()
    if display is None:
        return

    path = Path(__file__).with_name("style.css")
    if not path.exists():
        logger.warning("Stylesheet not found, using the plain system theme")
        return

    provider = Gtk.CssProvider()
    provider.load_from_path(str(path))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


class MainWindow(Adw.ApplicationWindow):
    """Shell of the redesigned interface: header bar, status card, page stack."""

    __gtype_name__ = "TengaMainWindow"

    def __init__(self, application: Adw.Application, context: AppContext) -> None:
        super().__init__(application=application, title="Tenga Proxy")
        self._context = context

        geometry = parse_geometry(getattr(context.config, "window_size", ""))
        self.set_default_size(geometry.width, geometry.height)
        # Без явного минимума libadwaita не может вычислить брейкпоинты.
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        if geometry.maximized:
            self.maximize()

        self._build_ui()
        self._install_breakpoint()
        self._register_row_actions()

        self.connect("close-request", self._on_close_request)
        context.proxy_state.add_listener(self._on_proxy_state_changed)
        self.refresh_status()
        self.refresh_pages()

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar)

        self.view_stack = Adw.ViewStack()
        self._add_pages()

        header = Adw.HeaderBar()
        # NARROW: подписи уходят под значки, поэтому третья вкладка не
        # обрезается на окне шириной чуть больше брейкпоинта.
        self.view_switcher = Adw.ViewSwitcher(
            stack=self.view_stack,
            policy=Adw.ViewSwitcherPolicy.NARROW,
        )
        header.set_title_widget(self.view_switcher)
        header.pack_start(self._build_add_button())
        header.pack_end(self._build_main_menu_button())
        header.pack_end(self._build_search_button())
        toolbar.add_top_bar(header)

        self.view_switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)
        toolbar.add_bottom_bar(self.view_switcher_bar)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.status_card = StatusCard()
        self.status_card.connect("action-clicked", self._on_status_action)
        content.append(self.status_card)

        self.view_stack.set_vexpand(True)
        content.append(self.view_stack)
        toolbar.set_content(content)

    def _add_pages(self) -> None:
        self.profiles_page = ProfilesPage()
        self.subscriptions_page = SubscriptionsPage()
        self.monitoring_page = MonitoringPage()
        self.monitoring_page.connect("refresh-requested", self._on_monitoring_refresh)
        self.profiles_page.connect("profile-activated", self._on_profile_activated)
        self.subscriptions_page.connect("subscription-activated", self._on_subscription_edit)
        self.subscriptions_page.connect("subscription-update", self._on_subscription_update)

        self.view_stack.add_titled_with_icon(
            self.profiles_page, "profiles", "Профили", "network-server-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.subscriptions_page, "subscriptions", "Подписки", "folder-download-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.monitoring_page, "monitoring", "Мониторинг", "utilities-system-monitor-symbolic"
        )

        self.view_stack.connect("notify::visible-child-name", self._on_page_changed)

    def _build_add_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Профиль из ссылки", "app.add-profile")
        menu.append("Профиль из буфера обмена", "app.add-profile-from-clipboard")
        menu.append("Подписка", "app.add-subscription")
        menu.append("Группа", "app.add-group")

        button = Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=menu)
        button.set_tooltip_text("Добавить")
        return button

    def _build_main_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Обновить подписки", "app.refresh-subscriptions")
        menu.append("Настройки", "app.settings")
        menu.append("Сочетания клавиш", "app.shortcuts")
        menu.append("О программе", "app.about")
        menu.append("Выход", "app.quit")

        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        button.set_tooltip_text("Главное меню")
        return button

    def _build_search_button(self) -> Gtk.ToggleButton:
        self.search_button = Gtk.ToggleButton(icon_name="system-search-symbolic")
        self.search_button.set_tooltip_text("Поиск (Ctrl+F)")
        self.search_button.connect("toggled", self._on_search_toggled)
        return self.search_button

    def _install_breakpoint(self) -> None:
        """Move the switcher into the bottom bar on narrow windows."""
        condition = Adw.BreakpointCondition.new_length(
            Adw.BreakpointConditionLengthType.MAX_WIDTH,
            NARROW_WIDTH,
            Adw.LengthUnit.SP,
        )
        breakpoint_ = Adw.Breakpoint.new(condition)
        breakpoint_.add_setter(self.view_switcher_bar, "reveal", True)
        breakpoint_.add_setter(self.view_switcher, "visible", False)
        self.add_breakpoint(breakpoint_)

    # --- действия строк ---

    _ROW_ACTIONS = (
        "connect-profile",
        "edit-profile",
        "delete-profile",
        "profile-routing",
        "test-profile",
        "toggle-group",
        "edit-group",
        "delete-group",
        "update-subscription",
        "edit-subscription",
        "delete-subscription",
    )

    def _register_row_actions(self) -> None:
        """Register the actions the row menus point at.

        Действия живут на окне, а не на приложении: они адресуют конкретную
        строку целым параметром, и держать их рядом со страницами, которые эти
        строки рисуют, проще, чем прокидывать выделение через приложение.
        """
        for name in self._ROW_ACTIONS:
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("i"))
            action.connect("activate", self._on_row_action, name)
            self.add_action(action)

    def _on_row_action(self, _action, parameter, name: str) -> None:
        handler = getattr(self, f"_row_{name.replace('-', '_')}")
        handler(parameter.get_int32())

    # профиль

    def _row_connect_profile(self, profile_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.connect_profile(profile_id)

    def _row_edit_profile(self, profile_id: int) -> None:
        from src.ui.dialogs.edit_profile import EditProfileDialog

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        dialog = EditProfileDialog(profile)
        dialog.connect("profile-saved", lambda _d: self._save_profiles())
        dialog.present(self)

    def _row_delete_profile(self, profile_id: int) -> None:
        from src.ui.dialogs.confirm import confirm_delete

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        app = self.get_application()
        confirm_delete(
            self,
            "Удалить профиль?",
            f"«{profile.name}» будет удалён безвозвратно.",
            lambda: app.delete_profile(profile_id) if app is not None else None,
        )

    def _row_profile_routing(self, profile_id: int) -> None:
        from src.ui.dialogs.profile_routing import ProfileRoutingDialog

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Профиль не найден")
            return

        dialog = ProfileRoutingDialog(profile)
        # У `Adw.PreferencesDialog` нет кнопки подтверждения: как и настройки
        # приложения, эти правки применяются при закрытии.
        dialog.connect("closed", lambda _d: self._save_routing(dialog))
        dialog.present(self)

    def _save_routing(self, dialog) -> None:
        dialog.save()
        self._save_profiles()

    def _row_test_profile(self, profile_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.test_latency_for(profile_id)

    # группа

    def _row_toggle_group(self, group_id: int) -> None:
        self.profiles_page.toggle_group(group_id)

    def _row_edit_group(self, group_id: int) -> None:
        group = self._context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return

        if group.is_subscription:
            self._row_edit_subscription(group_id)
            return

        from src.ui.dialogs.group import GroupDialog

        app = self.get_application()
        dialog = GroupDialog(group=group)
        dialog.connect(
            "group-ready",
            lambda _d, name: app.update_group(group_id, name=name) if app else None,
        )
        dialog.present(self)

    def _row_delete_group(self, group_id: int) -> None:
        from src.ui.dialogs.confirm import confirm_delete

        group = self._context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return

        app = self.get_application()
        count = len(self._context.profiles.get_profiles_in_group(group_id))
        confirm_delete(
            self,
            "Удалить группу?",
            f"«{group.name}» и {count} профилей внутри будут удалены безвозвратно.",
            lambda: app.delete_group(group_id) if app is not None else None,
        )

    # подписка

    def _row_update_subscription(self, group_id: int) -> None:
        self._on_subscription_update(None, group_id)

    def _row_edit_subscription(self, group_id: int) -> None:
        from src.ui.dialogs.subscription import SubscriptionDialog

        group = self._context.profiles.get_group(group_id)
        if group is None:
            self.toast("Подписка не найдена")
            return

        app = self.get_application()
        dialog = SubscriptionDialog(group=group)
        dialog.connect(
            "subscription-ready",
            lambda _d, name, url: (app.update_group(group_id, name=name, url=url) if app else None),
        )
        dialog.present(self)

    def _row_delete_subscription(self, group_id: int) -> None:
        self._row_delete_group(group_id)

    def _on_subscription_edit(self, _page, group_id: int) -> None:
        self._row_edit_subscription(group_id)

    def _save_profiles(self) -> None:
        app = self.get_application()
        if app is not None:
            app.save_profiles()

    # --- страницы ---

    SEARCHABLE_PAGES = ("profiles", "subscriptions")

    def refresh_pages(self) -> None:
        """Reload every page from the current store and proxy state."""
        store = self._context.profiles
        groups = store.groups
        profiles_by_group = {group_id: store.get_profiles_in_group(group_id) for group_id in groups}

        state = self._context.proxy_state
        active_id = state.started_profile_id if state.is_running else -1

        self.profiles_page.set_active_profile(active_id)
        self.profiles_page.set_data(groups, profiles_by_group)

        counts = {group_id: len(items) for group_id, items in profiles_by_group.items()}
        self.subscriptions_page.set_data(groups, counts)

        self.refresh_monitoring()

    def refresh_monitoring(self) -> None:
        """Redraw the monitoring page from the monitor and the active profile."""
        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()

        state = self._context.proxy_state
        profile = (
            self._context.profiles.get_profile(state.started_profile_id)
            if state.is_running
            else None
        )

        routing = getattr(profile, "routing_settings", None) or self._context.config.routing
        vpn_settings = getattr(profile, "vpn_settings", None)
        vpn_enabled = bool(
            vpn_settings
            and getattr(vpn_settings, "enabled", False)
            and getattr(vpn_settings, "connection_name", "")
        )

        self.monitoring_page.update(
            monitoring_view(
                status,
                routing,
                is_running=state.is_running,
                profile_found=profile is not None,
                vpn_enabled=vpn_enabled,
                # Активность VPN берётся из последней проверки монитора, а не
                # запрашивается у NetworkManager: перерисовка не должна ходить
                # в систему.
                vpn_is_up=vpn_enabled and status.vpn_ok,
            )
        )

    def set_search_enabled(self, enabled: bool) -> None:
        """Open or close the search bar of the visible page."""
        page = self._visible_search_page()
        if page is None:
            return
        page.set_search_enabled(enabled)

    def _visible_search_page(self):
        name = self.view_stack.get_visible_child_name()
        if name == "profiles":
            return self.profiles_page
        if name == "subscriptions":
            return self.subscriptions_page
        return None

    def _on_page_changed(self, _stack, _param) -> None:
        """Close the search of the page we just left and disable it where unused."""
        for page in (self.profiles_page, self.subscriptions_page):
            if page is not self._visible_search_page():
                page.set_search_enabled(False)

        searchable = self.view_stack.get_visible_child_name() in self.SEARCHABLE_PAGES
        self.search_button.set_sensitive(searchable)
        if not searchable:
            self.search_button.set_active(False)

    def _on_search_toggled(self, button: Gtk.ToggleButton) -> None:
        self.set_search_enabled(button.get_active())

    def _on_profile_activated(self, _page, profile_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.select_profile(profile_id)

    def _on_subscription_update(self, _page, group_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.update_subscription(group_id)

    def _on_monitoring_refresh(self, _page) -> None:
        monitor = self._context.monitor
        if monitor is not None:
            monitor.check_now()
        self.refresh_monitoring()

    def refresh_status(self) -> None:
        """Redraw the status card from the current proxy state."""
        state = self._context.proxy_state
        if state.is_running:
            profile = self._context.profiles.get_profile(state.started_profile_id)
            view = status_view(
                ConnectionState.CONNECTED,
                profile_name=profile.name if profile else "",
                latency_ms=getattr(profile, "latency_ms", None) if profile else None,
                upload_bytes=state.upload_bytes,
                download_bytes=state.download_bytes,
                mode=state.started_mode.upper(),
            )
        else:
            view = status_view(ConnectionState.DISCONNECTED)

        self.status_card.update(view)

    def show_connecting(self, profile_name: str = "") -> None:
        """Put the card into the intermediate state while xray-core starts."""
        self.status_card.update(status_view(ConnectionState.CONNECTING, profile_name=profile_name))

    def show_error(self, message: str) -> None:
        """Show a connection failure on the card."""
        self.status_card.update(status_view(ConnectionState.ERROR, error=message))

    def toast(self, text: str) -> None:
        """Show a transient message over the content."""
        self.toast_overlay.add_toast(Adw.Toast(title=text))

    def _on_status_action(self, _card: StatusCard) -> None:
        app = self.get_application()
        if app is not None:
            app.activate_action("toggle-connection", None)

    def _on_proxy_state_changed(self, _state) -> None:
        from gi.repository import GLib

        GLib.idle_add(self._refresh_status_idle)

    def _refresh_status_idle(self) -> bool:
        from gi.repository import GLib

        self.refresh_status()
        self.refresh_pages()
        return GLib.SOURCE_REMOVE

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        """Persist geometry once, on close (B12)."""
        self.save_geometry()
        self.detach()
        return False

    def detach(self) -> None:
        """Stop listening to the proxy state.

        Сигнал destroy приходит только при завершении процесса, поэтому
        отписка выполняется здесь: слушатель закрытого окна иначе обратился бы
        к уничтоженным виджетам при следующей смене состояния.
        """
        self._context.proxy_state.remove_listener(self._on_proxy_state_changed)

    def save_geometry(self) -> None:
        """Store the current size.

        Публичный метод: приложение вызывает его и при завершении по сигналу,
        когда close-request не эмитируется вовсе.
        """
        width, height = self.get_default_size()
        geometry = Geometry(width=width, height=height, maximized=self.is_maximized())
        self._context.config.window_size = format_geometry(geometry)
        try:
            self._context.save_config()
        except Exception as e:
            logger.warning("Could not persist window geometry: %s", e)
