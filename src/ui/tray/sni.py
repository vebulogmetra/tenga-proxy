"""org.kde.StatusNotifierItem and com.canonical.dbusmenu over Gio.DBus.

Своя реализация вместо AppIndicator3: та библиотека собрана против GTK3 и в
одном процессе с GTK4 не живёт. Здесь используется только `Gio`, так что модуль
работает и без дисплея.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from gi.repository import Gio, GLib

from src.ui.tray.dbusmenu import MenuItem, MenuModel
from src.ui.tray.variants import layout_variant, properties_variant

logger = logging.getLogger("tenga.ui.tray.sni")

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"

ITEM_PATH = "/StatusNotifierItem"
ITEM_INTERFACE = "org.kde.StatusNotifierItem"
MENU_PATH = "/MenuBar"
MENU_INTERFACE = "com.canonical.dbusmenu"

# Счётчик в имени: спецификация требует org.kde.StatusNotifierItem-<pid>-<nr>,
# а в одном процессе теоретически может жить несколько элементов.
_instance_counter = 0

ITEM_XML = """
<node>
  <interface name='org.kde.StatusNotifierItem'>
    <property name='Category' type='s' access='read'/>
    <property name='Id' type='s' access='read'/>
    <property name='Title' type='s' access='read'/>
    <property name='Status' type='s' access='read'/>
    <property name='IconName' type='s' access='read'/>
    <property name='IconThemePath' type='s' access='read'/>
    <property name='AttentionIconName' type='s' access='read'/>
    <property name='OverlayIconName' type='s' access='read'/>
    <property name='Menu' type='o' access='read'/>
    <property name='ItemIsMenu' type='b' access='read'/>
    <property name='ToolTip' type='(sa(iiay)ss)' access='read'/>
    <method name='Activate'>
      <arg type='i' name='x' direction='in'/>
      <arg type='i' name='y' direction='in'/>
    </method>
    <method name='SecondaryActivate'>
      <arg type='i' name='x' direction='in'/>
      <arg type='i' name='y' direction='in'/>
    </method>
    <method name='Scroll'>
      <arg type='i' name='delta' direction='in'/>
      <arg type='s' name='orientation' direction='in'/>
    </method>
    <signal name='NewIcon'/>
    <signal name='NewStatus'><arg type='s' name='status'/></signal>
    <signal name='NewTitle'/>
    <signal name='NewToolTip'/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name='com.canonical.dbusmenu'>
    <property name='Version' type='u' access='read'/>
    <property name='TextDirection' type='s' access='read'/>
    <property name='Status' type='s' access='read'/>
    <property name='IconThemePath' type='as' access='read'/>
    <method name='GetLayout'>
      <arg type='i' name='parentId' direction='in'/>
      <arg type='i' name='recursionDepth' direction='in'/>
      <arg type='as' name='propertyNames' direction='in'/>
      <arg type='u' name='revision' direction='out'/>
      <arg type='(ia{sv}av)' name='layout' direction='out'/>
    </method>
    <method name='GetGroupProperties'>
      <arg type='ai' name='ids' direction='in'/>
      <arg type='as' name='propertyNames' direction='in'/>
      <arg type='a(ia{sv})' name='properties' direction='out'/>
    </method>
    <method name='GetProperty'>
      <arg type='i' name='id' direction='in'/>
      <arg type='s' name='name' direction='in'/>
      <arg type='v' name='value' direction='out'/>
    </method>
    <method name='Event'>
      <arg type='i' name='id' direction='in'/>
      <arg type='s' name='eventId' direction='in'/>
      <arg type='v' name='data' direction='in'/>
      <arg type='u' name='timestamp' direction='in'/>
    </method>
    <method name='AboutToShow'>
      <arg type='i' name='id' direction='in'/>
      <arg type='b' name='needUpdate' direction='out'/>
    </method>
    <signal name='LayoutUpdated'>
      <arg type='u' name='revision'/>
      <arg type='i' name='parent'/>
    </signal>
    <signal name='ItemsPropertiesUpdated'>
      <arg type='a(ia{sv})' name='updatedProps'/>
      <arg type='a(ias)' name='removedProps'/>
    </signal>
  </interface>
</node>
"""


class StatusNotifierItem:
    """A tray item published on the session bus."""

    def __init__(
        self,
        connection: Gio.DBusConnection | None = None,
        *,
        item_id: str = "tenga-proxy",
        title: str = "Tenga Proxy",
    ) -> None:
        global _instance_counter
        _instance_counter += 1

        self._connection = connection
        self.item_id = item_id
        self.title = title
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-{_instance_counter}"

        self._icon_name = ""
        self._icon_theme_path = ""
        self._status = "Active"
        self._tooltip = ""
        self._menu = MenuModel([])
        self._revision = 1

        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None

        self._name_id = 0
        self._item_reg = 0
        self._menu_reg = 0
        self._watch_id = 0
        self.is_registered = False

    # --- публикация ---

    def publish(self) -> None:
        """Export both objects, take the bus name and look for a watcher."""
        if self._connection is None:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
        self._item_reg = self._connection.register_object(
            ITEM_PATH, item_info.interfaces[0], self._on_item_call, self._on_item_get, None
        )

        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML)
        self._menu_reg = self._connection.register_object(
            MENU_PATH, menu_info.interfaces[0], self._on_menu_call, self._on_menu_get, None
        )

        self._name_id = Gio.bus_own_name_on_connection(
            self._connection, self.bus_name, Gio.BusNameOwnerFlags.NONE, None, None
        )

        # Watcher может появиться позже нас (перезапуск панели, вход в сессию),
        # поэтому не одна попытка регистрации, а наблюдение за именем.
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )

    def shutdown(self) -> None:
        """Remove the item from the bus."""
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._name_id:
            Gio.bus_unown_name(self._name_id)
            self._name_id = 0
        if self._connection is not None:
            for reg in (self._item_reg, self._menu_reg):
                if reg:
                    self._connection.unregister_object(reg)
            self._item_reg = 0
            self._menu_reg = 0
        self.is_registered = False

    def _on_watcher_appeared(self, connection, _name, _owner) -> None:
        connection.call(
            WATCHER_NAME,
            WATCHER_PATH,
            WATCHER_INTERFACE,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self.bus_name,)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            self._on_registered,
        )

    def _on_registered(self, source, result) -> None:
        try:
            source.call_finish(result)
        except Exception as e:
            logger.info("Tray watcher refused the item: %s", e)
            return
        self.is_registered = True
        logger.info("Tray item registered as %s", self.bus_name)

    def _on_watcher_vanished(self, _connection, _name) -> None:
        self.is_registered = False

    # --- свойства ---

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        """Change the icon and tell the panel to re-read it."""
        self._icon_name = icon_name
        if theme_path:
            self._icon_theme_path = theme_path
        self._emit_item_signal("NewIcon", None)

    def set_status(self, status: str) -> None:
        """Change the item status (Active / Passive / NeedsAttention)."""
        self._status = status
        self._emit_item_signal("NewStatus", GLib.Variant("(s)", (status,)))

    def set_tooltip(self, text: str) -> None:
        """Change the text shown when the pointer rests on the icon."""
        self._tooltip = text
        self._emit_item_signal("NewToolTip", None)

    def set_menu(self, items: list[MenuItem]) -> None:
        """Replace the whole menu and bump the revision."""
        self._menu = MenuModel(items)
        self._revision += 1
        self._emit_menu_signal("LayoutUpdated", GLib.Variant("(ui)", (self._revision, 0)))

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        """Install what runs when a menu entry is clicked."""
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        """Install what runs on a left click on the icon."""
        self._on_primary = handler

    def _emit_item_signal(self, name: str, params) -> None:
        if self._connection is None or not self._item_reg:
            return
        self._connection.emit_signal(None, ITEM_PATH, ITEM_INTERFACE, name, params)

    def _emit_menu_signal(self, name: str, params) -> None:
        if self._connection is None or not self._menu_reg:
            return
        self._connection.emit_signal(None, MENU_PATH, MENU_INTERFACE, name, params)

    # --- обработчики org.kde.StatusNotifierItem ---

    def _on_item_get(self, _connection, _sender, _path, _interface, prop):
        if prop == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if prop == "Id":
            return GLib.Variant("s", self.item_id)
        if prop == "Title":
            return GLib.Variant("s", self.title)
        if prop == "Status":
            return GLib.Variant("s", self._status)
        if prop == "IconName":
            return GLib.Variant("s", self._icon_name)
        if prop == "IconThemePath":
            return GLib.Variant("s", self._icon_theme_path)
        if prop in ("AttentionIconName", "OverlayIconName"):
            return GLib.Variant("s", "")
        if prop == "Menu":
            return GLib.Variant("o", MENU_PATH)
        if prop == "ItemIsMenu":
            # False: левый клик обязан открывать окно, а не меню.
            return GLib.Variant("b", False)
        if prop == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("", [], self.title, self._tooltip))
        return None

    def _on_item_call(self, _connection, _sender, _path, _interface, method, _params, invocation):
        if method == "Activate" and self._on_primary is not None:
            self._on_primary()
        invocation.return_value(None)

    # --- обработчики com.canonical.dbusmenu ---

    def _on_menu_get(self, _connection, _sender, _path, _interface, prop):
        if prop == "Version":
            return GLib.Variant("u", 3)
        if prop == "TextDirection":
            return GLib.Variant("s", "ltr")
        if prop == "Status":
            return GLib.Variant("s", "normal")
        if prop == "IconThemePath":
            return GLib.Variant("as", [self._icon_theme_path] if self._icon_theme_path else [])
        return None

    def _on_menu_call(self, _connection, _sender, _path, _interface, method, params, invocation):
        if method == "GetLayout":
            parent_id, depth, _names = params.unpack()
            invocation.return_value(layout_variant(self._menu, parent_id, self._revision, depth))
            return

        if method == "GetGroupProperties":
            ids, names = params.unpack()
            invocation.return_value(properties_variant(self._menu, list(ids), list(names)))
            return

        if method == "GetProperty":
            item_id, name = params.unpack()
            value = self._menu.properties(item_id).get(name, "")
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", str(value)),)))
            return

        if method == "Event":
            item_id, event_id, _data, _timestamp = params.unpack()
            if event_id == "clicked":
                self._activate_item(item_id)
            invocation.return_value(None)
            return

        if method == "AboutToShow":
            # Меню перестраивается при смене состояния, панели ничего
            # перечитывать не нужно.
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return

        invocation.return_value(None)

    def _activate_item(self, item_id: int) -> None:
        item = self._menu.find(item_id)
        if item is None or not item.action or self._on_activate is None:
            return
        self._on_activate(item.action, item.target)
