"""Main application window (GTK4 + libadwaita)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk

from src.ui.logic.geometry import (
    MIN_HEIGHT,
    MIN_WIDTH,
    Geometry,
    format_geometry,
    parse_geometry,
)
from src.ui.logic.status import ConnectionState, status_view
from src.ui.widgets.status_card import StatusCard

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.window")

NARROW_WIDTH = 550


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

        self.connect("close-request", self._on_close_request)
        context.proxy_state.add_listener(self._on_proxy_state_changed)
        self.refresh_status()

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
        pages = (
            ("profiles", "Профили", "network-server-symbolic", "Профилей пока нет"),
            ("subscriptions", "Подписки", "folder-download-symbolic", "Подписок пока нет"),
            ("monitoring", "Мониторинг", "utilities-system-monitor-symbolic", "Нет данных"),
        )
        for name, title, icon, placeholder in pages:
            # Страницы наполняются на этапе 2, пока это заглушки.
            page = Adw.StatusPage(title=placeholder, icon_name=icon)
            self.view_stack.add_titled_with_icon(page, name, title, icon)

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
