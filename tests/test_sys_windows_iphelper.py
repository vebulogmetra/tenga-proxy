from __future__ import annotations

import ctypes as C
import socket

import pytest

from src.sys.windows import iphelper
from src.sys.windows.netinfo import default_route


class FakeAPI:
    def __init__(self):
        self.adapter = iphelper.AdapterAddress()
        self.adapter.index = 12
        self.adapter.alias = "Ethernet"
        self.adapter.description = "Physical"
        self.adapter.status = 1
        self.adapter.iftype = 6
        self.adapter.metric4 = 25
        self.table = iphelper.RouteTable()
        self.table.count = 1
        row = self.table.rows[0]
        row.index = 12
        row.prefix.length = 0
        row.metric = 5
        row.hop.raw[4:8] = socket.inet_aton("192.0.2.1")
        self.freed = False
        self.attempts = 0
        self.adapter_error = 0
        self.route_error = 0

    def GetAdaptersAddresses(self, _family, _flags, _reserved, buffer, size):
        self.attempts += 1
        if self.attempts == 1:
            C.cast(size, C.POINTER(iphelper.U32)).contents.value = 32768
            return 111
        C.memmove(buffer, C.byref(self.adapter), C.sizeof(self.adapter))
        return self.adapter_error

    def GetIpForwardTable2(self, _family, output):
        C.cast(output, C.POINTER(C.c_void_p)).contents.value = C.addressof(self.table)
        return self.route_error

    def FreeMibTable(self, _table):
        self.freed = True


def test_snapshot_retries_buffer_and_adds_interface_metric():
    api = FakeAPI()
    snapshot = iphelper.read_snapshot(api)
    route = default_route(snapshot)
    assert api.attempts == 2 and api.freed
    assert route.metric == 30
    assert route.nexthop == "192.0.2.1"


def test_tunnel_interface_cannot_be_default_direct_route():
    api = FakeAPI()
    api.adapter.iftype = 131
    assert default_route(iphelper.read_snapshot(api)) is None


@pytest.mark.parametrize("operation", ["adapter", "route"])
def test_native_errors_are_not_an_empty_success(operation):
    api = FakeAPI()
    setattr(api, f"{operation}_error", 5)
    with pytest.raises(OSError, match="failed"):
        iphelper.read_snapshot(api)


def test_only_default_and_split_routes_are_included():
    api = FakeAPI()
    api.table.rows[0].prefix.length = 1
    assert iphelper.read_snapshot(api).routes[0].prefix == "0.0.0.0/1"
    api.table.rows[0].prefix.length = 24
    assert not iphelper.read_snapshot(api).routes


def test_ipv4_address_chain():
    raw = C.create_string_buffer(b"\x02\x00\x00\x00" + socket.inet_aton("192.0.2.3") + b"\x00" * 8)
    node = iphelper.AddressNode()
    node.socket.address = C.addressof(raw)
    node.socket.length = 16
    assert iphelper._addresses(C.pointer(node)) == ["192.0.2.3"]


def test_native_table_is_freed_when_conversion_fails(monkeypatch):
    api = FakeAPI()
    monkeypatch.setattr(iphelper.socket, "inet_ntop", lambda *_a: int("invalid"))
    with pytest.raises(ValueError, match="invalid"):
        iphelper.read_snapshot(api)
    assert api.freed


def test_tun_readiness_requires_up_adapter_with_address(monkeypatch):
    from src.sys.windows.netinfo import Adapter, NetSnapshot

    adapter = Adapter("xray0", 40, "Down", "Wintun")
    monkeypatch.setattr(iphelper, "read_snapshot", lambda: NetSnapshot([adapter]))
    config = {"inbounds": [{"protocol": "tun", "settings": {"name": "xray0"}}]}
    assert not iphelper.tun_ready(config)
    adapter.status = "Up"
    assert not iphelper.tun_ready(config)
    adapter.ipv4 = ["198.18.0.1"]
    assert iphelper.tun_ready(config)
    assert iphelper.tun_ready({"inbounds": []})
