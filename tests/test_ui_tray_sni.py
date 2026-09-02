"""Элемент трея на приватной шине: свойства, меню, события, watcher."""

from __future__ import annotations

import pytest
from gi.repository import Gio, GLib

from src.ui.tray.dbusmenu import MenuItem, separator
from src.ui.tray.sni import StatusNotifierItem

WATCHER_XML = """
<node>
  <interface name='org.kde.StatusNotifierWatcher'>
    <method name='RegisterStatusNotifierItem'>
      <arg type='s' name='service' direction='in'/>
    </method>
    <property name='IsStatusNotifierHostRegistered' type='b' access='read'/>
  </interface>
</node>
"""

BUS_FLAGS = (
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
)


class FakeWatcher:
    """Minimal org.kde.StatusNotifierWatcher for the tests."""

    def __init__(self, connection):
        self.registered: list[str] = []
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        connection.register_object(
            "/StatusNotifierWatcher",
            info.interfaces[0],
            self._on_call,
            self._on_get,
            None,
        )
        Gio.bus_own_name_on_connection(
            connection,
            "org.kde.StatusNotifierWatcher",
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

    def _on_call(self, _c, _sender, _path, _iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            self.registered.append(params.unpack()[0])
        invocation.return_value(None)

    def _on_get(self, _c, _sender, _path, _iface, _prop):
        return GLib.Variant("b", True)


@pytest.fixture
def menu_items():
    return [
        MenuItem("Статус: Отключено", enabled=False),
        separator(),
        MenuItem("Подключить", action="app.connect"),
        MenuItem("Выход", action="app.quit"),
    ]


@pytest.fixture
def item(bus_connection, menu_items, pump):
    """A published tray item on the private bus."""
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-proxy-test")
    sni.set_menu(menu_items)
    sni.publish()
    pump()
    yield sni
    sni.shutdown()


def _get(dbus_call, connection, bus_name, path, interface, prop):
    return dbus_call(
        connection,
        bus_name,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        GLib.Variant("(ss)", (interface, prop)),
    ).unpack()[0]


def test_the_bus_name_follows_the_specification(item):
    # org.kde.StatusNotifierItem-<pid>-<nr> — иначе панель имя не распознает.
    assert item.bus_name.startswith("org.kde.StatusNotifierItem-")


def test_the_item_owns_its_bus_name(item, bus_connection, dbus_call):
    owned = dbus_call(
        bus_connection,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (item.bus_name,)),
    ).unpack()[0]

    assert owned is True


def test_the_id_property_is_exported(item, bus_connection, dbus_call):
    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Id",
    )

    assert value == "tenga-proxy-test"


def test_the_category_is_application_status(item, bus_connection, dbus_call):
    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Category",
    )

    assert value == "ApplicationStatus"


def test_the_menu_property_points_at_the_menu_object(item, bus_connection, dbus_call):
    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Menu",
    )

    assert value == "/MenuBar"


def test_the_status_property_starts_active(item, bus_connection, dbus_call):
    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Status",
    )

    assert value == "Active"


def test_set_icon_changes_the_exported_icon_name(item, bus_connection, dbus_call, pump):
    item.set_icon("tenga-proxy-connected")
    pump()

    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "IconName",
    )

    assert value == "tenga-proxy-connected"


def test_set_tooltip_is_exported_as_the_tooltip_tuple(item, bus_connection, dbus_call, pump):
    item.set_tooltip("Подключено: Работа")
    pump()

    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "ToolTip",
    )

    # Формат ToolTip: (icon, pixmaps, title, description).
    assert value[3] == "Подключено: Работа"


def test_get_layout_returns_the_menu_tree(item, bus_connection, dbus_call):
    revision, root = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()

    labels = [child[1].get("label", "") for child in root[2]]

    assert revision >= 1
    assert labels == ["Статус: Отключено", "", "Подключить", "Выход"]


def test_get_group_properties_answers_for_one_item(item, bus_connection, dbus_call):
    (pairs,) = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetGroupProperties",
        GLib.Variant("(aias)", ([3], [])),
    ).unpack()

    assert pairs[0][1]["label"] == "Подключить"


def test_the_dbusmenu_version_property_is_three(item, bus_connection, dbus_call):
    value = _get(
        dbus_call,
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Version",
    )

    assert value == 3


def test_a_clicked_event_invokes_the_handler(item, bus_connection, dbus_call):
    fired: list[tuple] = []
    item.set_on_activate(lambda action, target: fired.append((action, target)))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (3, "clicked", GLib.Variant("s", ""), 0)),
    )

    assert fired == [("app.connect", None)]


def test_an_event_on_an_item_without_an_action_is_ignored(item, bus_connection, dbus_call):
    fired: list = []
    item.set_on_activate(lambda action, _target: fired.append(action))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (1, "clicked", GLib.Variant("s", ""), 0)),
    )

    assert fired == []


def test_an_event_on_an_unknown_id_does_not_raise(item, bus_connection, dbus_call):
    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (999, "clicked", GLib.Variant("s", ""), 0)),
    )


def test_a_menu_event_carries_the_target(bus_connection, dbus_call, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-target")
    sni.set_menu([MenuItem("Профиль", action="app.select-profile", target=17)])
    sni.publish()
    pump()

    fired: list[tuple] = []
    sni.set_on_activate(lambda action, target: fired.append((action, target)))
    try:
        dbus_call(
            bus_connection,
            sni.bus_name,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "Event",
            GLib.Variant("(isvu)", (1, "clicked", GLib.Variant("s", ""), 0)),
        )
    finally:
        sni.shutdown()

    assert fired == [("app.select-profile", 17)]


def test_about_to_show_reports_no_update_needed(item, bus_connection, dbus_call):
    (needs_update,) = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "AboutToShow",
        GLib.Variant("(i)", (0,)),
    ).unpack()

    # Меню перестраивается по состоянию, а не по запросу панели.
    assert needs_update is False


def test_activate_invokes_the_primary_handler(item, bus_connection, dbus_call):
    fired: list = []
    item.set_on_primary(lambda: fired.append(True))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Activate",
        GLib.Variant("(ii)", (0, 0)),
    )

    assert fired == [True]


def test_setting_a_new_menu_bumps_the_revision(item, bus_connection, dbus_call, pump):
    before = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()[0]

    item.set_menu([MenuItem("Другое")])
    pump()

    after = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()[0]

    # Панель перечитывает меню, только когда номер ревизии вырос.
    assert after > before


def test_the_item_registers_with_a_watcher_that_is_already_there(bus_connection, private_bus, pump):
    watcher_connection = Gio.DBusConnection.new_for_address_sync(private_bus, BUS_FLAGS, None, None)
    watcher = FakeWatcher(watcher_connection)
    pump()

    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-registered")
    sni.publish()
    pump(0.5)
    try:
        assert sni.bus_name in watcher.registered
    finally:
        sni.shutdown()


def test_the_item_registers_when_the_watcher_appears_later(bus_connection, private_bus, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-late")
    sni.publish()
    pump()

    assert sni.is_registered is False

    watcher_connection = Gio.DBusConnection.new_for_address_sync(private_bus, BUS_FLAGS, None, None)
    watcher = FakeWatcher(watcher_connection)
    pump(0.5)
    try:
        # Переподключение важнее всего при перезапуске панели: элемент обязан
        # вернуться в трей сам.
        assert sni.bus_name in watcher.registered
    finally:
        sni.shutdown()


def test_publishing_without_a_watcher_does_not_raise(bus_connection, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-nowatcher")
    sni.publish()
    pump()
    try:
        assert sni.is_registered is False
    finally:
        sni.shutdown()


def test_shutdown_releases_the_bus_name(bus_connection, dbus_call, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-gone")
    sni.publish()
    pump()
    name = sni.bus_name

    sni.shutdown()
    pump()

    owned = dbus_call(
        bus_connection,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (name,)),
    ).unpack()[0]

    assert owned is False


def test_shutdown_twice_is_safe(bus_connection, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-twice")
    sni.publish()
    pump()

    sni.shutdown()
    sni.shutdown()
