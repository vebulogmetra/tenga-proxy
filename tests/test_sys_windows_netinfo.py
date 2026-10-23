"""Разбор снимка сети Windows: адаптеры, адреса, DNS, маршруты по умолчанию."""

from __future__ import annotations

import json

import pytest

from src.sys.windows import netinfo

SNAPSHOT = {
    "adapters": [
        {"alias": "Ethernet", "index": 12, "status": "Up", "description": "Intel(R) Ethernet"},
        {"alias": "xray0", "index": 40, "status": "Up", "description": "Wintun Userspace Tunnel"},
        {"alias": "Office", "index": 41, "status": "Up", "description": "WAN Miniport (IKEv2)"},
    ],
    "ips": [
        {"alias": "Ethernet", "ip": "192.168.0.154"},
        {"alias": "xray0", "ip": "198.18.0.1"},
        {"alias": "Office", "ip": "10.8.0.5"},
    ],
    "dns": [
        {"alias": "Ethernet", "servers": ["192.168.0.1", "fe80::1"]},
        {"alias": "Office", "servers": ["10.8.0.1"]},
    ],
    "routes": [
        {"alias": "xray0", "index": 40, "nexthop": "0.0.0.0", "metric": 0, "ifmetric": 5},
        {"alias": "Ethernet", "index": 12, "nexthop": "192.168.0.1", "metric": 0, "ifmetric": 25},
    ],
}


def test_parse_builds_adapters_with_addresses():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    ethernet = snapshot.adapter("Ethernet")
    assert ethernet.ipv4 == ["192.168.0.154"]
    assert ethernet.dns == ["192.168.0.1", "fe80::1"]


def test_single_objects_are_accepted_as_lists():
    """PowerShell сворачивает массив из одного элемента в объект."""
    data = dict(SNAPSHOT, ips={"alias": "Ethernet", "ip": "192.168.0.154"})

    assert netinfo.parse_snapshot(json.dumps(data)).adapter("Ethernet").ipv4 == ["192.168.0.154"]


def test_tunnel_adapters_are_recognised():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    assert netinfo.is_tunnel(snapshot.adapter("xray0"))
    assert netinfo.is_tunnel(snapshot.adapter("Office"))
    assert not netinfo.is_tunnel(snapshot.adapter("Ethernet"))


def test_default_route_skips_tunnels_and_exclusions():
    snapshot = netinfo.parse_snapshot(json.dumps(SNAPSHOT))

    route = netinfo.default_route(snapshot, exclude=("xray0",))

    assert route.alias == "Ethernet"
    assert route.nexthop == "192.168.0.1"


def test_default_route_none_when_only_tunnels():
    data = dict(SNAPSHOT, routes=[SNAPSHOT["routes"][0]])

    assert netinfo.default_route(netinfo.parse_snapshot(json.dumps(data))) is None


def test_garbage_gives_empty_snapshot():
    assert netinfo.parse_snapshot("not json").adapters == []


def test_snapshot_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(
        netinfo, "run_json", lambda script: calls.append(script) or json.dumps(SNAPSHOT)
    )
    netinfo.invalidate()

    netinfo.snapshot()
    netinfo.snapshot()
    netinfo.invalidate()

    assert len(calls) == 1


def test_non_object_items_are_skipped():
    data = dict(SNAPSHOT, adapters=["junk", *SNAPSHOT["adapters"]])

    assert len(netinfo.parse_snapshot(json.dumps(data)).adapters) == 3


@pytest.mark.windows
def test_real_snapshot_has_adapters_and_default_route():
    netinfo.invalidate()
    snapshot = netinfo.snapshot()

    assert snapshot.adapters
    route = netinfo.default_route(snapshot)
    assert route is not None and route.alias
