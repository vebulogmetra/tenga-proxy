"""Main application window (GTK4 + libadwaita)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from src.core.config import get_asset_path
from src.ui.logic.appearance import (
    COMPACT_HEIGHT,
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    normalize_theme,
)
from src.ui.logic.geometry import (
    MIN_HEIGHT,
    MIN_WIDTH,
    Geometry,
    format_geometry,
    parse_geometry,
)
from src.ui.logic.menus import MAIN_MENU
from src.ui.logic.monitoring_view import format_last_check, monitoring_view
from src.ui.logic.status import (
    BLOCKED_BANNER,
    RELEASE_BLOCK_LABEL,
    ConnectionPresentation,
    ConnectionState,
    connecting_view,
    health_text,
    is_traffic_blocked,
    mode_text,
    status_view,
)
from src.ui.pages.monitoring import MonitoringPage
from src.ui.pages.profiles import ProfilesPage
from src.ui.widgets.status_card import StatusCard

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.window")

APP_ICON = "tenga-proxy"

PAGE_TITLES = {"servers": "Серверы", "monitoring": "Диагностика"}


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
        logger.warning("Stylesheet not found: %s", path)
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(str(path))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def apply_theme(theme: str | None) -> None:
    """Force the light or dark scheme, or follow the system one."""
    scheme = {
        "light": Adw.ColorScheme.FORCE_LIGHT,
        "dark": Adw.ColorScheme.FORCE_DARK,
    }.get(normalize_theme(theme), Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)


def load_icons() -> None:
    """Make the bundled application icon resolvable by name.

    Иконка лежит в собственном каталоге темы, а не только в системной: при
    запуске из исходников и на Windows в системной теме её имени нет.
    После регистрации `tenga-proxy` доступен обычным поиском по имени —
    им пользуются и окно, и диалог «О программе».
    """
    display = Gdk.Display.get_default()
    if display is None:
        return

    path = get_asset_path("theme")
    if not path.exists():
        logger.warning("Icon theme not found at %s, using the system theme", path)
        return

    theme = Gtk.IconTheme.get_for_display(display)
    theme.add_search_path(str(path))


class MainWindow(Adw.ApplicationWindow):
    """Status panel on the left; servers or diagnostics on the right, as in Qt."""

    __gtype_name__ = "TengaMainWindow"

    def __init__(self, application: Adw.Application, context: AppContext) -> None:
        super().__init__(application=application, title="Veblock")
        self.set_icon_name(APP_ICON)
        self._context = context
        self._presentation = ConnectionPresentation()

        geometry = parse_geometry(getattr(context.config, "window_size", ""))
        self.set_default_size(geometry.width, geometry.height)
        # Без явного минимума libadwaita не может вычислить брейкпоинты; он же
        # не даёт сжать панель и список дальше общего с Qt минимума.
        self.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        if geometry.maximized:
            self.maximize()

        self._build_ui()
        self._install_breakpoint()
        self._register_row_actions()

        self.connect("close-request", self._on_close_request)
        self.connect("notify::visible", self._sync_log_timer)
        context.proxy_state.add_listener(self._on_proxy_state_changed)
        self.refresh_status()
        self.refresh_pages()

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.set_content(self.toast_overlay)
        self.toast_overlay.set_child(toolbar)

        self._add_pages()
        toolbar.add_top_bar(self._build_header())

        # Панель состояния слева, страницы справа — как в Qt.
        self.columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.status_card = StatusCard()
        self.status_card.connect("action-clicked", self._on_status_action)
        self.panel_clamp = Adw.Clamp(
            child=self.status_card,
            maximum_size=PANEL_MAX_WIDTH,
            tightening_threshold=PANEL_MIN_WIDTH,
            hexpand=False,
        )
        self.columns.append(self.panel_clamp)
        self.columns.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.pending_banner = Adw.Banner(
            title="Изменения применятся после переподключения",
            button_label="Переподключить",
            revealed=False,
        )
        self.pending_banner.connect(
            "button-clicked", lambda _banner: self.get_application().reconnect_current()
        )
        right.append(self.pending_banner)
        self.blocked_banner = Adw.Banner(
            title=BLOCKED_BANNER,
            button_label=RELEASE_BLOCK_LABEL,
            revealed=False,
        )
        self.blocked_banner.connect(
            "button-clicked",
            lambda _banner: self.get_application().activate_action("release-block", None),
        )
        right.append(self.blocked_banner)

        self.right_stack = Gtk.Stack(
            vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        self.right_stack.set_margin_top(8)
        self.right_stack.set_margin_bottom(8)
        self.right_stack.set_margin_start(8)
        self.right_stack.set_margin_end(8)

        servers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        servers.append(self.profiles_page)
        footer = Gtk.Box(spacing=8)
        self.diagnostics_toggle = Gtk.ToggleButton(label="Диагностика")
        self.diagnostics_toggle.connect("toggled", self._on_diagnostics_toggled)
        footer.append(self.diagnostics_toggle)
        footer.append(Gtk.Box(hexpand=True))
        self.latency_button = Gtk.Button(label="Проверить задержку", action_name="app.test-latency")
        footer.append(self.latency_button)
        servers.append(footer)

        self.right_stack.add_named(servers, "servers")
        # Стек берёт высоту самой высокой страницы: без прокрутки диагностика
        # (около 620 px) не давала окну сжаться до MIN_HEIGHT и срезала низ.
        monitoring = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        monitoring.set_child(self.monitoring_page)
        self.right_stack.add_named(monitoring, "monitoring")
        right.append(self.right_stack)
        self.columns.append(right)
        toolbar.set_content(self.columns)

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        self.back_button = Gtk.Button(label="← Серверы", visible=False)
        self.back_button.connect("clicked", lambda _b: self.show_servers())
        header.pack_start(self.back_button)

        self.page_title = Gtk.Label(label=PAGE_TITLES["servers"])
        self.page_title.add_css_class("title")
        header.set_title_widget(self.page_title)

        menu = Gio.Menu()
        for name, label in MAIN_MENU:
            menu.append(label, f"app.{name}")
        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        self.menu_button.set_tooltip_text("Главное меню")
        header.pack_end(self.menu_button)
        self.settings_button = Gtk.Button(label="Настройки", action_name="app.settings")
        header.pack_end(self.settings_button)
        return header

    def _add_pages(self) -> None:
        self.profiles_page = ProfilesPage()
        self.monitoring_page = MonitoringPage()
        self.monitoring_page.connect("refresh-requested", self._on_monitoring_refresh)
        self.monitoring_page.connect(
            "diagnostics-requested",
            lambda _page: self.get_application().activate_action("network-diagnostics"),
        )
        self.profiles_page.connect("profile-activated", self._on_profile_activated)
        self.profiles_page.connect("selection-changed", lambda _page: self.refresh_status())
        self.profiles_page.connect("switch-clicked", self._on_switch_clicked)
        self.profiles_page.connect(
            "profile-ping", lambda _page, profile_id: self._row_test_profile(profile_id)
        )

    def _install_breakpoint(self) -> None:
        """Shrink the status panel on a low window; the logo stays visible."""
        condition = Adw.BreakpointCondition.new_length(
            Adw.BreakpointConditionLengthType.MAX_HEIGHT, COMPACT_HEIGHT, Adw.LengthUnit.SP
        )
        breakpoint_ = Adw.Breakpoint.new(condition)
        breakpoint_.add_setter(self.status_card, "compact", True)
        self.add_breakpoint(breakpoint_)

    # --- переключение страниц ---

    def _on_diagnostics_toggled(self, button: Gtk.ToggleButton) -> None:
        name = "monitoring" if button.get_active() else "servers"
        self.right_stack.set_visible_child_name(name)
        self.page_title.set_text(PAGE_TITLES[name])
        self.back_button.set_visible(name == "monitoring")
        self._sync_log_timer()
        if name == "servers":
            self.profiles_page.list_view.grab_focus()

    def _sync_log_timer(self, *_args) -> None:
        """One log timer, running only while the diagnostics page is on screen."""
        self.monitoring_page.set_active(self.diagnostics_toggle.get_active() and self.get_visible())

    def show_servers(self) -> None:
        """Return to the server list, keeping its search, selection and scroll."""
        self.diagnostics_toggle.set_active(False)

    def show_diagnostics(self) -> None:
        self.diagnostics_toggle.set_active(True)

    def show_log(self) -> None:
        """«Журнал…» в меню: диагностика с фокусом в журнале."""
        self.show_diagnostics()
        self.monitoring_page.focus_log()

    def focus_search(self) -> None:
        """Ctrl+F: back to the servers and into the search field."""
        self.show_servers()
        self.profiles_page.focus_search()

    # --- действия строк ---

    _ROW_ACTIONS = (
        "connect-profile",
        "edit-profile",
        "delete-profile",
        "profile-routing",
        "test-profile",
        "test-group",
        "connect-best",
        "keep-working",
        "toggle-group",
        "edit-group",
        "delete-group",
        "update-subscription",
        "edit-subscription",
        "delete-subscription",
        "open-subscription-page",
        "open-subscription-support",
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

    def _present_dialog(self, dialog) -> None:
        """Show a dialog through the application's single slot.

        Окно не показывает диалоги само: приложение держит их по одному,
        иначе повторное действие клало бы форму поверх формы.
        """
        app = self.get_application()
        if app is None:
            dialog.present(self)
            return
        app.present_dialog(dialog)

    # профиль

    def _row_connect_profile(self, profile_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.connect_profile(profile_id)

    def _row_edit_profile(self, profile_id: int) -> None:
        from src.ui.dialogs.edit_profile import EditProfileDialog

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Сервер не найден")
            return

        dialog = EditProfileDialog(profile)
        dialog.connect("profile-saved", lambda _d: self._save_profiles())
        self._present_dialog(dialog)

    def _row_delete_profile(self, profile_id: int) -> None:
        from src.ui.dialogs.confirm import build_delete_confirmation

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Сервер не найден")
            return

        app = self.get_application()
        self._present_dialog(
            build_delete_confirmation(
                "Удалить сервер?",
                f"«{profile.name}» будет удалён безвозвратно.",
                lambda: app.delete_profile(profile_id) if app is not None else None,
            )
        )

    def _row_profile_routing(self, profile_id: int) -> None:
        from src.ui.dialogs.profile_routing import ProfileRoutingDialog

        profile = self._context.profiles.get_profile(profile_id)
        if profile is None:
            self.toast("Сервер не найден")
            return

        from src.ui.logic.routing_import import effective_routing

        shared = effective_routing(self._context.config.routing, self._context.config_dir)
        dialog = ProfileRoutingDialog(profile, shared)
        # У `Adw.PreferencesDialog` нет кнопки подтверждения: как и настройки
        # приложения, эти правки применяются при закрытии.
        dialog.connect("routing-saved", lambda _d: self._save_profiles())
        self._present_dialog(dialog)

    def _save_routing(self, dialog) -> None:
        if dialog.save() is not False:
            self._save_profiles()

    def _row_keep_working(self, group_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.keep_working_profiles(group_id)

    def _row_test_profile(self, profile_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.test_latency_for(profile_id)

    # группа

    def _row_test_group(self, group_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.test_latency_for_group(group_id)

    def _row_connect_best(self, group_id: int) -> None:
        app = self.get_application()
        if app is not None:
            app.connect_best(group_id)

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
        self._present_dialog(dialog)

    def _row_delete_group(self, group_id: int) -> None:
        from src.ui.dialogs.confirm import build_delete_confirmation

        group = self._context.profiles.get_group(group_id)
        if group is None:
            self.toast("Группа не найдена")
            return

        app = self.get_application()
        count = len(self._context.profiles.get_profiles_in_group(group_id))
        self._present_dialog(
            build_delete_confirmation(
                "Удалить группу?",
                f"«{group.name}» и {count} серверов внутри будут удалены безвозвратно.",
                lambda: app.delete_group(group_id) if app is not None else None,
            )
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
        self._present_dialog(dialog)

    def _row_delete_subscription(self, group_id: int) -> None:
        self._row_delete_group(group_id)

    def _row_open_subscription_page(self, group_id: int) -> None:
        from src.sub.metadata import is_safe_web_page_url

        self._open_subscription_link(group_id, "sub_web_page_url", is_safe_web_page_url)

    def _row_open_subscription_support(self, group_id: int) -> None:
        from src.sub.metadata import is_safe_support_url

        self._open_subscription_link(group_id, "sub_support_url", is_safe_support_url)

    def _open_subscription_link(self, group_id: int, field: str, is_safe) -> None:
        """Open a link the provider attached to the subscription.

        Проверка повторяется перед самым открытием: ссылка лежит в файле
        профилей, который можно изменить в обход приложения.
        """
        group = self._context.profiles.get_group(group_id)
        url = getattr(group, field, "") if group is not None else ""
        if not url or not is_safe(url):
            self.toast("Ссылка недоступна")
            return
        self._launch_uri(url)

    def _launch_uri(self, uri: str) -> None:
        Gtk.UriLauncher.new(uri).launch(self, None, None)

    def _save_profiles(self) -> None:
        app = self.get_application()
        if app is not None:
            app.save_profiles()

    # --- страницы ---

    def refresh_pages(self) -> None:
        """Reload every page from the current store and proxy state."""
        store = self._context.profiles
        groups = store.groups
        profiles_by_group = {group_id: store.get_profiles_in_group(group_id) for group_id in groups}

        state = self._context.proxy_state
        active_id = state.started_profile_id if state.is_running else -1
        self._rendered_active = (state.is_running, state.started_profile_id)

        self.profiles_page.set_active_profile(active_id)
        self.profiles_page.set_data(groups, profiles_by_group)

        # Список подписок живёт в настройках: открытый диалог видит изменения сразу.
        app = self.get_application()
        dialog = getattr(app, "settings_dialog", None)
        if dialog is not None:
            dialog.refresh_subscriptions()

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
        own_rules = getattr(profile, "routing_settings", None) is not None
        vpn_settings = getattr(profile, "vpn_settings", None)
        vpn_enabled = bool(
            vpn_settings
            and getattr(vpn_settings, "enabled", False)
            and getattr(vpn_settings, "connection_name", "")
        )

        checked = self._presentation.check_done(
            running=state.is_running,
            active_id=state.started_profile_id if state.is_running else None,
            last_check_time=status.last_check_time,
        )
        self.monitoring_page.update(
            monitoring_view(
                status,
                routing,
                is_running=state.is_running,
                profile_found=profile is not None,
                own_rules=own_rules,
                vpn_enabled=vpn_enabled,
                # Активность VPN берётся из последней проверки монитора, а не
                # запрашивается у NetworkManager: перерисовка не должна ходить
                # в систему.
                vpn_is_up=vpn_enabled and status.vpn_ok,
                checked=checked,
            )
        )

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
        from src.ui.logic.settings_state import pending_settings

        self.pending_banner.set_revealed(pending_settings(self._context))
        state = self._context.proxy_state
        blocked = is_traffic_blocked(state)
        self.blocked_banner.set_revealed(blocked)
        store = self._context.profiles
        selected_id = self.profiles_page.get_selected_profile_id()
        selected = store.get_profile(selected_id) if selected_id is not None else None
        if state.is_running:
            profile = store.get_profile(state.started_profile_id)
        elif blocked:
            # Тот же сервер, что подключит логотип.
            profile = store.get_profile(state.blocked_profile_id)
        else:
            # Тот же порядок, что у connect_selected(): выделение, иначе последний.
            profile = selected or store.last_used_profile()
        mode = state.started_mode if state.is_running else self._context.config.proxy_mode
        app = self.get_application()
        controller = getattr(app, "controller", None)
        busy = controller is not None and controller.connection_busy()
        view = self._presentation.resolve(
            running=state.is_running,
            active_id=state.started_profile_id,
            busy=busy,
            profile_name=profile.name if profile else "",
            mode=mode_text(mode),
            upload=state.upload_bytes,
            download=state.download_bytes,
            latency=getattr(profile, "latency_ms", None) if profile and state.is_running else None,
            has_profiles=bool(store.profiles),
            can_connect=profile is not None,
            blocked=blocked,
        )
        self.status_card.update(view)

        switch_to = (
            selected.name
            if selected is not None and state.is_running and selected.id != state.started_profile_id
            else ""
        )
        self.profiles_page.set_switch_target(switch_to, enabled=not busy)

        monitor = self._context.monitor
        status = monitor.status if monitor is not None else _EmptyStatus()
        checked = self._presentation.check_done(
            running=state.is_running,
            active_id=state.started_profile_id if state.is_running else None,
            last_check_time=status.last_check_time,
        )
        self.status_card.set_health(
            health_text(
                running=state.is_running,
                checked=checked,
                proxy_ok=status.proxy_ok,
                last_check=format_last_check(status.last_check_time),
                error=self._presentation.error,
            )
        )

    def show_connecting(self, profile_name: str = "", note: str = "") -> None:
        """Put the card into the intermediate state while xray-core starts."""
        # Контроллер зовёт это до запуска потока, connection_busy() ещё False,
        # поэтому карточка рисуется напрямую, а не через refresh_status().
        self._presentation.begin("connect", profile_name, note)
        self.status_card.update(connecting_view(profile_name, note))

    def show_error(self, message: str) -> None:
        """Show a connection failure; it stays until the next attempt or state change."""
        state = self._context.proxy_state
        self._presentation.fail(
            message, (state.is_running, state.started_profile_id if state.is_running else None)
        )
        self.refresh_status()

    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        """Show a transient message over the content, optionally with an undo-like button."""
        toast = Adw.Toast(title=text)
        if button and action:
            toast.set_button_label(button)
            toast.set_action_name(action)
        self.toast_overlay.add_toast(toast)

    def _on_status_action(self, _card: StatusCard) -> None:
        app = self.get_application()
        if app is not None:
            app.activate_action("toggle-connection", None)

    def _on_switch_clicked(self, _page: ProfilesPage) -> None:
        selected_id = self.profiles_page.get_selected_profile_id()
        app = self.get_application()
        if app is not None and selected_id is not None:
            app.activate_action("connect-profile", GLib.Variant.new_int32(selected_id))

    def _on_proxy_state_changed(self, _state) -> None:
        from gi.repository import GLib

        GLib.idle_add(self._refresh_status_idle)

    def _refresh_status_idle(self) -> bool:
        from gi.repository import GLib

        # Слушателей будит и счётчик трафика, раз в секунду. Строки пересобираются
        # только при смене активного сервера: пересборка закрывает открытое в них меню.
        state = self._context.proxy_state
        changed = self._rendered_active != (state.is_running, state.started_profile_id)
        self.refresh_status()
        if changed:
            self.refresh_pages()
        else:
            self.refresh_monitoring()
        return GLib.SOURCE_REMOVE

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        """With a tray the window hides; without one closing quits, as in Qt."""
        self.save_geometry()
        app = self.get_application()
        tray_visible = app is not None and getattr(app, "tray_visible", lambda: False)()
        if tray_visible and getattr(self._context.config, "close_to_tray", True):
            self.set_visible(False)
            return True
        self.detach()
        if app is not None:
            app.quit()
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
