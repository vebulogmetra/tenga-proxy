"""Что о VPN нужно правилам блокировки трафика: тип, адрес сервера, интерфейс."""

from __future__ import annotations

import socket
import subprocess
from types import SimpleNamespace

import pytest

from src.sys.linux import vpn

OPENVPN_DATA = (
    "auth = SHA256, ca = /home/u/ca.pem, connection-type = tls, dev = tun, "
    "remote = vpn.example.org\\:993, remote-cert-tls = server"
)


def fake_nmcli(monkeypatch, fields: dict[str, str], *, addr_output: str = "", returncode: int = 0):
    def run(cmd, **_kwargs):
        if cmd[0] == "nmcli":
            return subprocess.CompletedProcess(
                cmd, returncode, stdout=fields.get(cmd[2], ""), stderr=""
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=addr_output, stderr="")

    monkeypatch.setattr(vpn.subprocess, "run", run)


def fake_dns(monkeypatch, answers: dict[str, list[str]]):
    def getaddrinfo(host, _port, **_kwargs):
        if host not in answers:
            raise socket.gaierror("no such host")
        return [(0, 0, 0, "", (address, 0)) for address in answers[host]]

    monkeypatch.setattr(vpn.socket, "getaddrinfo", getaddrinfo)


def test_connection_type_comes_from_network_manager(monkeypatch):
    fake_nmcli(monkeypatch, {"connection.type": "wireguard\n"})

    assert vpn.vpn_connection_type("corp") == "wireguard"


def test_unknown_connection_has_no_type(monkeypatch):
    fake_nmcli(monkeypatch, {}, returncode=10)

    assert vpn.vpn_connection_type("corp") == ""


def test_missing_nmcli_is_not_an_error(monkeypatch):
    def run(*_a, **_k):
        raise FileNotFoundError

    monkeypatch.setattr(vpn.subprocess, "run", run)

    assert vpn.vpn_connection_type("corp") == ""
    assert vpn.vpn_server_addresses("corp") == ()


def test_openvpn_remote_with_a_port_is_resolved_to_both_families(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": OPENVPN_DATA})
    fake_dns(monkeypatch, {"vpn.example.org": ["203.0.113.5", "2001:db8::5"]})

    assert vpn.vpn_server_addresses("corp") == ("203.0.113.5", "2001:db8::5")


def test_other_plugins_keep_the_address_in_gateway(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": "gateway = 198.51.100.7, user = me"})
    fake_dns(monkeypatch, {"198.51.100.7": ["198.51.100.7"]})

    assert vpn.vpn_server_addresses("corp") == ("198.51.100.7",)


@pytest.mark.parametrize(
    ("remote", "host"),
    [
        ("vpn.example.org\\:993\\:udp", "vpn.example.org"),
        ("[2001:db8::9]\\:1194", "2001:db8::9"),
        ("2001\\:db8\\:\\:9", "2001:db8::9"),
        ("198.51.100.7", "198.51.100.7"),
    ],
)
def test_remote_forms(monkeypatch, remote, host):
    fake_nmcli(monkeypatch, {"vpn.data": f"remote = {remote}"})
    fake_dns(monkeypatch, {host: ["203.0.113.5"]})

    assert vpn.vpn_server_addresses("corp") == ("203.0.113.5",)


def test_several_remotes_are_all_kept_without_repeats(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": "remote = a.example\\:1\\, b.example\\:2 a.example"})
    fake_dns(monkeypatch, {"a.example": ["203.0.113.1"], "b.example": ["203.0.113.2"]})

    assert vpn.vpn_server_addresses("corp") == ("203.0.113.1", "203.0.113.2")


def test_unresolved_name_gives_no_address(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": OPENVPN_DATA})
    fake_dns(monkeypatch, {})

    assert vpn.vpn_server_addresses("corp") == ()


def test_scoped_address_does_not_reach_the_rules(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": "gateway = gw.example"})
    fake_dns(monkeypatch, {"gw.example": ["fe80::1%eth0", "203.0.113.5"]})

    assert vpn.vpn_server_addresses("corp") == ("203.0.113.5",)


def test_connection_without_vpn_data_has_no_addresses(monkeypatch):
    fake_nmcli(monkeypatch, {"vpn.data": ""})

    assert vpn.vpn_server_addresses("corp") == ()


ADDR_OUTPUT = """\
1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
3: wlp1s0    inet 192.168.0.154/24 brd 192.168.0.255 scope global wlp1s0\\       valid_lft
7: tun9    inet 10.20.0.10/24 scope global tun9\\       valid_lft forever preferred_lft forever
"""


def test_tunnel_is_the_interface_holding_the_connections_address(monkeypatch):
    """Не первый tun*: номер интерфейса ни о чём не говорит."""
    fake_nmcli(monkeypatch, {"IP4.ADDRESS": "10.20.0.10/24\n"}, addr_output=ADDR_OUTPUT)

    assert vpn.vpn_tunnel_interface("corp") == "tun9"


def test_tunnel_with_several_addresses(monkeypatch):
    fake_nmcli(
        monkeypatch, {"IP4.ADDRESS": "172.16.0.1/24 | 10.20.0.10/24"}, addr_output=ADDR_OUTPUT
    )

    assert vpn.vpn_tunnel_interface("corp") == "tun9"


def test_inactive_connection_has_no_tunnel(monkeypatch):
    fake_nmcli(monkeypatch, {"IP4.ADDRESS": ""}, addr_output=ADDR_OUTPUT)

    assert vpn.vpn_tunnel_interface("corp") is None


def test_address_on_no_interface_gives_no_tunnel(monkeypatch):
    """Запасного «первого tun*» нет: чужой VPN в правила не попадает."""
    fake_nmcli(monkeypatch, {"IP4.ADDRESS": "10.99.0.1/24"}, addr_output=ADDR_OUTPUT)

    assert vpn.vpn_tunnel_interface("corp") is None


def test_core_gets_the_tunnel_of_the_connection_and_not_a_foreign_one(monkeypatch):
    """Чужой tun0 стоит раньше: ядро не должно привязаться к нему."""
    monkeypatch.setattr(vpn, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(vpn, "vpn_tunnel_interface", lambda _name: "tun1")

    def must_not_search(*_args, **_kwargs):
        raise AssertionError("Интерфейс уже известен, искать tun* незачем")

    monkeypatch.setattr(vpn.subprocess, "run", must_not_search)

    assert vpn.get_vpn_interface("corp") == "tun1"


def test_unknown_tunnel_falls_back_to_the_search(monkeypatch):
    monkeypatch.setattr(vpn, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(vpn, "vpn_tunnel_interface", lambda _name: None)
    links = "5: tun3: <POINTOPOINT,UP> mtu 1500"

    def run(command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=links if command[0] == "ip" else "", stderr="")

    monkeypatch.setattr(vpn.subprocess, "run", run)

    assert vpn.get_vpn_interface("corp") == "tun3"
