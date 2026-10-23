"""Windows-реализация интерфейсов и DNS поверх снимка сети."""

from __future__ import annotations

import json

import pytest

from src.sys.windows import netinfo, resolver, tun_dns, tun_route, vpn
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


def test_vpn_connect_is_not_available_yet():
    assert vpn.list_vpn_connections() == []
    assert vpn.connect_vpn("Office") is False


def test_tun_routes_report_why_they_fail():
    ok, state, error = tun_route.apply_tun_routes("xray0", "example.com")

    assert (ok, state) == (False, None)
    assert "служб" in error


def test_restoring_nothing_is_fine():
    assert tun_route.restore_tun_routes(None) == (True, "")


def test_tun_dns_reports_why_it_fails():
    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert ok is False
    assert error
