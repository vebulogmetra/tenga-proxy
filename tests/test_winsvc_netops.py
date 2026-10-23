"""Команды netsh и PowerShell для маршрутов, DNS и NRPT."""

from __future__ import annotations

import pytest

from src.winsvc import netops


def test_route_add_on_link():
    assert netops.route_add("0.0.0.0/1", 40) == [
        "netsh",
        "interface",
        "ipv4",
        "add",
        "route",
        "prefix=0.0.0.0/1",
        "interface=40",
        "metric=1",
        "store=active",
    ]


def test_route_add_via_gateway():
    assert "nexthop=192.168.0.1" in netops.route_add("1.2.3.4/32", 12, "192.168.0.1")


def test_route_delete():
    assert netops.route_delete("0.0.0.0/1", 40) == [
        "netsh",
        "interface",
        "ipv4",
        "delete",
        "route",
        "prefix=0.0.0.0/1",
        "interface=40",
        "store=active",
    ]


def test_set_dns_uses_index():
    cmd = netops.set_dns(40, "1.1.1.1")

    assert "name=40" in cmd
    assert "address=1.1.1.1" in cmd


@pytest.mark.parametrize("bad", ["1.1.1.1; calc", "x", ""])
def test_addresses_are_validated(bad):
    with pytest.raises(ValueError, match="bad IPv4 address"):
        netops.set_dns(40, bad)


def test_index_must_be_positive_int():
    with pytest.raises(ValueError, match="bad interface index"):
        netops.route_delete("0.0.0.0/1", 0)


def test_nrpt_add_script_mentions_comment_and_server():
    script = netops.nrpt_add_script("1.1.1.1")

    assert "Add-DnsClientNrptRule" in script
    assert "'1.1.1.1'" in script
    assert netops.NRPT_COMMENT in script


def test_nrpt_remove_requires_guid():
    with pytest.raises(ValueError, match="bad NRPT rule name"):
        netops.nrpt_remove_script("'; Remove-Item C:\\ -Recurse; '")


def test_undo_maps_journal_entries_to_commands():
    calls = []
    net = netops.NetOps(run=lambda cmd: calls.append(cmd) or True, powershell=lambda _script: "")

    net.undo({"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40})

    assert calls == [netops.route_delete("0.0.0.0/1", 40)]
