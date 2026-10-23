"""Windows-реализация интерфейсов и DNS поверх снимка сети."""

from __future__ import annotations

import json

import pytest

from src.sys.windows import netinfo, resolver, vpn
from tests.test_sys_windows_netinfo import SNAPSHOT


@pytest.fixture(autouse=True)
def fake_network(monkeypatch):
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(SNAPSHOT)))


def test_default_interface_is_physical():
    assert vpn.get_default_interface(exclude=("xray0",)) == "Ethernet"


def test_default_interface_respects_vpn_exclusion():
    assert vpn.get_default_interface("Ethernet", exclude=("xray0",)) is None


def test_interfaces_are_listed_by_alias():
    assert vpn.list_network_interfaces() == ["Ethernet", "Office", "xray0"]


def test_interface_ip():
    assert vpn.get_vpn_interface_ip("Office") == "10.8.0.5"


def test_dns_servers_drop_ipv6():
    assert resolver.system_dns_servers("Ethernet") == ["192.168.0.1"]


@pytest.fixture
def vpn_sources(monkeypatch):
    from src.sys.windows import ras, service_client

    state = {"ras": {"Office": True, "Home": False}, "wg_running": {"home": False}}

    class FakeClient:
        def __init__(self):
            self.calls = []

        def call(self, cmd, **args):
            self.calls.append((cmd, args))
            if cmd == "wireguard.list":
                return {"tunnels": ["home"]}
            return {}

    client = FakeClient()
    monkeypatch.setattr(ras, "connections", lambda: dict(state["ras"]))
    monkeypatch.setattr(ras, "connect", lambda name: state["ras"].__setitem__(name, True) or True)
    monkeypatch.setattr(ras, "disconnect", lambda _name: True)
    monkeypatch.setattr(service_client, "get_client", lambda: client)
    monkeypatch.setattr(
        vpn, "_wireguard_running", lambda name: state["wg_running"].get(name, False)
    )
    monkeypatch.setattr(vpn, "INTERFACE_WAIT_SECONDS", 0)
    return state, client


def test_list_merges_ras_and_wireguard(vpn_sources):
    assert vpn.list_vpn_connections() == ["Home", "Office", "home"]


def test_ras_active(vpn_sources):
    assert vpn.is_vpn_active("Office") is True
    assert vpn.is_vpn_active("Home") is False


def test_ras_connect(vpn_sources):
    assert vpn.connect_vpn("Home") is True


def test_wireguard_connect_goes_to_service(vpn_sources, monkeypatch):
    _state, client = vpn_sources
    monkeypatch.setattr(vpn, "_wait_interface", lambda _name: None)

    assert vpn.connect_vpn("home") is True
    assert ("wireguard.up", {"name": "home"}) in client.calls


def test_wireguard_disconnect_goes_to_service(vpn_sources):
    _state, client = vpn_sources

    assert vpn.disconnect_vpn("home") is True
    assert ("wireguard.down", {"name": "home"}) in client.calls


def test_unknown_connection_cannot_be_controlled(vpn_sources):
    assert vpn.connect_vpn("OpenVPN TAP") is False
    assert vpn.disconnect_vpn("OpenVPN TAP") is False


def test_foreign_adapter_that_is_up_counts_as_active(vpn_sources, monkeypatch):
    # OpenVPN и прочие: управлять нельзя, но интерфейс профиль использует.
    data = dict(SNAPSHOT, ips=[*SNAPSHOT["ips"], {"alias": "TAP", "ip": "10.7.0.2", "index": 60}])
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(data)))

    assert vpn.is_vpn_active("TAP") is True
    assert vpn.is_vpn_active("Nope") is False


def test_vpn_interface_is_the_connection_alias(vpn_sources, monkeypatch):
    data = dict(SNAPSHOT, ips=[*SNAPSHOT["ips"], {"alias": "Home", "ip": "10.9.0.2", "index": 55}])
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(data)))

    assert vpn.get_vpn_interface("Home") == "Home"
    assert vpn.get_vpn_interface("Nope") is None


def test_vpn_dns(vpn_sources):
    assert vpn.get_vpn_dns_servers("Office") == ["10.8.0.1"]
