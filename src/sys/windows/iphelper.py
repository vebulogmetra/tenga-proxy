"""Чтение IPv4-сети через IP Helper API, без процессов и локализованного вывода.

Структуры: IP_ADAPTER_ADDRESSES_LH и MIB_IPFORWARD_ROW2 из Windows SDK.
Размеры целых заданы явно: ctypes.c_ulong на Linux имеет другой размер.
"""

from __future__ import annotations

import ctypes as C
import socket

U32 = C.c_uint32
U64 = C.c_uint64
U8 = C.c_ubyte


class SocketAddress(C.Structure):
    _fields_ = [("address", C.c_void_p), ("length", C.c_int32)]


class AddressNode(C.Structure):
    pass


AddressNode._fields_ = [
    ("alignment", U64),
    ("next", C.POINTER(AddressNode)),
    ("socket", SocketAddress),
]


class AdapterAddress(C.Structure):
    pass


AdapterAddress._fields_ = [
    ("length", U32),
    ("index", U32),
    ("next", C.POINTER(AdapterAddress)),
    ("name", C.c_char_p),
    ("unicast", C.POINTER(AddressNode)),
    ("anycast", C.c_void_p),
    ("multicast", C.c_void_p),
    ("dns", C.POINTER(AddressNode)),
    ("suffix", C.c_wchar_p),
    ("description", C.c_wchar_p),
    ("alias", C.c_wchar_p),
    ("physical", U8 * 8),
    ("physical_length", U32),
    ("flags", U32),
    ("mtu", U32),
    ("iftype", U32),
    ("status", U32),
    ("ipv6_index", U32),
    ("zones", U32 * 16),
    ("prefix", C.c_void_p),
    ("tx_speed", U64),
    ("rx_speed", U64),
    ("wins", C.c_void_p),
    ("gateway", C.c_void_p),
    ("metric4", U32),
    ("metric6", U32),
]


class SockaddrInet(C.Union):
    _fields_ = [("family", C.c_uint16), ("raw", U8 * 28), ("alignment", U32)]


class Prefix(C.Structure):
    _fields_ = [("address", SockaddrInet), ("length", U8)]


class RouteRow(C.Structure):
    _fields_ = [
        ("luid", U64),
        ("index", U32),
        ("prefix", Prefix),
        ("hop", SockaddrInet),
        ("site_length", U8),
        ("valid", U32),
        ("preferred", U32),
        ("metric", U32),
        ("protocol", U32),
        ("loopback", U8),
        ("autoconfigure", U8),
        ("publish", U8),
        ("immortal", U8),
        ("age", U32),
        ("origin", U32),
    ]


class RouteTable(C.Structure):
    _fields_ = [("count", U32), ("rows", RouteRow * 1)]


def _api():
    api = C.WinDLL("iphlpapi.dll", winmode=0x800)
    api.GetAdaptersAddresses.argtypes = [U32, U32, C.c_void_p, C.c_void_p, C.POINTER(U32)]
    api.GetAdaptersAddresses.restype = U32
    api.GetIpForwardTable2.argtypes = [C.c_uint16, C.POINTER(C.c_void_p)]
    api.GetIpForwardTable2.restype = U32
    api.FreeMibTable.argtypes = [C.c_void_p]
    api.FreeMibTable.restype = None
    return api


def _addresses(node):
    result = []
    while node:
        address = node.contents.socket
        if address.address and address.length >= 8:
            raw = C.string_at(address.address, 8)
            if int.from_bytes(raw[:2], "little") == socket.AF_INET:
                result.append(socket.inet_ntop(socket.AF_INET, raw[4:8]))
        node = node.contents.next
    return result


def read_snapshot(api=None):
    from src.sys.windows.netinfo import Adapter, NetSnapshot, Route

    api = api or _api()
    size = U32(16384)
    for _attempt in range(4):
        buffer = C.create_string_buffer(size.value)
        # SKIP_ANYCAST | SKIP_MULTICAST | INCLUDE_ALL_INTERFACES
        error = api.GetAdaptersAddresses(socket.AF_INET, 0x106, None, buffer, C.byref(size))
        if error != 111:  # ERROR_BUFFER_OVERFLOW: network changed during enumeration
            break
    if error == 232:  # ERROR_NO_DATA
        return NetSnapshot()
    if error:
        raise OSError(error, "GetAdaptersAddresses failed")
    adapters, metrics = [], {}
    node = C.cast(buffer, C.POINTER(AdapterAddress))
    while node:
        item = node.contents
        if item.iftype != 24 and item.index and item.alias:  # exclude software loopback
            adapters.append(
                Adapter(
                    item.alias,
                    item.index,
                    "Up" if item.status == 1 else "Down",
                    item.description or "",
                    _addresses(item.unicast),
                    _addresses(item.dns),
                    listed=item.iftype not in (23, 131),
                )
            )
            metrics[item.index] = item.metric4
        node = item.next
    by_index = {item.index: item for item in adapters}
    table = C.c_void_p()
    error = api.GetIpForwardTable2(socket.AF_INET, C.byref(table))
    if error:
        raise OSError(error, "GetIpForwardTable2 failed")
    routes = []
    try:
        if table.value:
            count = C.cast(table, C.POINTER(RouteTable)).contents.count
            rows = (RouteRow * count).from_address(table.value + RouteTable.rows.offset)
            for row in rows:
                prefix = socket.inet_ntop(socket.AF_INET, bytes(row.prefix.address.raw[4:8]))
                network = f"{prefix}/{row.prefix.length}"
                adapter = by_index.get(row.index)
                if adapter and network in ("0.0.0.0/0", "0.0.0.0/1"):
                    routes.append(
                        Route(
                            adapter.alias,
                            row.index,
                            socket.inet_ntop(socket.AF_INET, bytes(row.hop.raw[4:8])),
                            row.metric + metrics[row.index],
                            network,
                        )
                    )
    finally:
        if table.value:
            api.FreeMibTable(table)
    return NetSnapshot(adapters, routes)


def tun_ready(config: dict) -> bool:
    """Адаптер уже поднят и получил IPv4; маршруты служба применит следующим шагом."""
    names = [
        item.get("settings", {}).get("name")
        for item in config.get("inbounds", [])
        if item.get("protocol") == "tun"
    ]
    if not names:
        return True
    if any(not name for name in names):
        return False
    snapshot = read_snapshot()
    return all(
        (adapter := snapshot.adapter(name)) is not None
        and adapter.status == "Up"
        and bool(adapter.ipv4)
        for name in names
    )
