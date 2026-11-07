"""Привязка сокета к интерфейсу: логика на подделках, настоящая опция — на живой Windows."""

from __future__ import annotations

import socket
import struct
import subprocess
import sys

import pytest

from src.sys.linux import netbind as linux
from src.sys.windows import netbind as windows
from src.sys.windows import netinfo


class FakeSocket:
    def __init__(self, family=socket.AF_INET):
        self.family = family
        self.options = []

    def setsockopt(self, *option):
        self.options.append(option)


def test_linux_binds_by_device_name_with_terminating_zero():
    sock = FakeSocket()
    linux.socket_binder("wlan0")(sock)
    assert sock.options == [(socket.SOL_SOCKET, linux.SO_BINDTODEVICE, b"wlan0\0")]


@pytest.fixture
def sys_net(tmp_path, monkeypatch):
    monkeypatch.setattr(linux, "SYS_CLASS_NET", tmp_path)
    (tmp_path / "eth0").mkdir()
    (tmp_path / "eth0" / "device").mkdir()
    (tmp_path / "wlan0" / "wireless").mkdir(parents=True)
    (tmp_path / "xray0").mkdir()
    (tmp_path / "xray0" / "tun_flags").write_text("0x1001\n")
    return tmp_path


def test_linux_interface_kinds(sys_net):
    assert linux.interface_kind("wlan0") == "WIFI"
    assert linux.interface_kind("eth0") == "ETHERNET"
    assert linux.interface_kind("xray0") == "OTHER"


def test_linux_physical_interface_excludes_tunnels_by_kernel_flag(sys_net, monkeypatch):
    seen = []
    monkeypatch.setattr(linux, "get_default_interface", lambda exclude: seen.append(exclude) or "e")
    assert linux.physical_interface(exclude=["tun7"]) == "e"
    assert seen == [["tun7", "xray0"]]


@pytest.mark.parametrize(
    ("routes", "expected"),
    [
        ("default dev xray0 scope link\n", "xray0"),
        ("default via 10.0.0.1 dev eth0\n", None),
        ("default via 10.0.0.1 dev eth0 metric 600\ndefault dev xray0 metric 50\n", "xray0"),
        ("", None),
        (
            "0.0.0.0/1 dev xray0 scope link\n128.0.0.0/1 dev xray0 scope link\n"
            "default via 10.0.0.1 dev eth0 metric 600\n",
            "xray0",
        ),
        ("10.0.0.0/24 dev xray0 scope link\ndefault via 10.0.0.1 dev eth0\n", None),
    ],
)
def test_linux_active_tunnel_comes_from_the_route(sys_net, monkeypatch, routes, expected):
    done = subprocess.CompletedProcess([], 0, stdout=routes, stderr="")
    monkeypatch.setattr(linux.subprocess, "run", lambda *_a, **_k: done)
    assert linux.active_tunnel_interface() == expected


def test_linux_active_tunnel_survives_missing_ip(sys_net, monkeypatch):
    def missing(*_a, **_k):
        raise FileNotFoundError("ip")

    monkeypatch.setattr(linux.subprocess, "run", missing)
    assert linux.active_tunnel_interface() is None


def _snapshot(monkeypatch, index=7):
    adapter = netinfo.Adapter("Wi-Fi", index, "Up", "Intel Wireless 802.11")
    snapshot = type(
        "S", (), {"adapter": lambda _self, alias: adapter if alias == "Wi-Fi" else None}
    )
    monkeypatch.setattr(netinfo, "snapshot", snapshot)


def test_windows_ipv4_index_is_in_network_byte_order(monkeypatch):
    _snapshot(monkeypatch)
    sock = FakeSocket()
    windows.socket_binder("Wi-Fi")(sock)
    assert sock.options == [(socket.IPPROTO_IP, windows.IP_UNICAST_IF, struct.pack("!I", 7))]


def test_windows_ipv6_index_is_in_host_byte_order(monkeypatch):
    _snapshot(monkeypatch)
    sock = FakeSocket(socket.AF_INET6)
    windows.socket_binder("Wi-Fi")(sock)
    assert sock.options == [(socket.IPPROTO_IPV6, windows.IPV6_UNICAST_IF, 7)]


def test_windows_missing_adapter_is_an_error_not_an_unbound_socket(monkeypatch):
    _snapshot(monkeypatch)
    binder = windows.socket_binder("Ethernet")
    with pytest.raises(OSError, match="gone"):
        binder(FakeSocket())


def test_windows_adapter_is_resolved_once_not_for_every_socket(monkeypatch):
    """Снимок сети — это запуск PowerShell: на каждый сокет пробы ждали бы его под блокировкой."""
    _snapshot(monkeypatch)
    queries = []
    real = netinfo.snapshot

    def counting():
        queries.append(1)
        return real()

    monkeypatch.setattr(netinfo, "snapshot", counting)
    binder = windows.socket_binder("Wi-Fi")
    for _ in range(3):
        binder(FakeSocket())
    assert len(queries) == 1


def _routed_snapshot(monkeypatch, routes):
    import json

    data = {
        "adapters": [
            {"alias": "Ethernet", "index": 12, "status": "Up", "description": "Intel Ethernet"},
            {
                "alias": "xray0",
                "index": 40,
                "status": "Up",
                "description": "Wintun Userspace Tunnel",
            },
        ],
        "ips": [],
        "dns": [],
        "routes": routes,
    }
    snapshot = netinfo.parse_snapshot(json.dumps(data))
    monkeypatch.setattr(netinfo, "snapshot", lambda: snapshot)


PHYSICAL = {"alias": "Ethernet", "index": 12, "nexthop": "192.168.0.1", "metric": 0, "ifmetric": 25}
SPLIT = {"alias": "xray0", "index": 40, "prefix": "0.0.0.0/1", "nexthop": "0.0.0.0", "metric": 0,
         "ifmetric": 1}  # fmt: skip


def test_windows_binding_is_confirmed_by_the_physical_default_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT, PHYSICAL])

    assert windows.binding_confirmed("Ethernet") is True
    assert windows.binding_confirmed("Wi-Fi") is False


def test_windows_binding_is_not_confirmed_without_a_default_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT])

    assert windows.binding_confirmed("Ethernet") is False


def test_windows_active_tunnel_is_found_by_the_split_route(monkeypatch):
    _routed_snapshot(monkeypatch, [SPLIT, PHYSICAL])

    assert windows.active_tunnel_interface() == "xray0"


def test_windows_no_tunnel_without_split_routes(monkeypatch):
    _routed_snapshot(monkeypatch, [PHYSICAL])

    assert windows.active_tunnel_interface() is None


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="нужна настоящая Windows")
def test_real_unicast_if_keeps_the_socket_on_the_adapter():
    """Опция принята, адрес источника — с этого адаптера. UDP connect пакетов не шлёт.

    На машине без TUN маршрут и так идёт через этот адаптер: под настоящим TUN опцию
    проверяет `tests/integration/`.
    """
    interface = windows.physical_interface()
    if interface is None:
        pytest.skip("нет сети")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        windows.socket_binder(interface)(sock)
        sock.connect(("192.0.2.1", 9))
        assert sock.getsockname()[0] in windows.interface_addresses(interface)


@pytest.mark.parametrize(
    ("output", "confirmed"),
    [
        ("default via 192.0.2.1 proto dhcp metric 600 \n", True),
        ("", False),
    ],
)
def test_linux_binding_needs_a_default_route_on_the_interface(
    monkeypatch, rp_filter, output, confirmed
):
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr("src.sys.linux.netbind.subprocess.run", run)
    assert linux.binding_confirmed("eth0") is confirmed
    assert calls == [["ip", "route", "show", "default", "dev", "eth0"]]


def test_linux_binding_is_not_confirmed_when_ip_fails(monkeypatch, rp_filter):
    def run(*_args, **_kwargs):
        raise OSError("no ip")

    monkeypatch.setattr("src.sys.linux.netbind.subprocess.run", run)
    assert linux.binding_confirmed("eth0") is False


@pytest.fixture
def rp_filter(tmp_path, monkeypatch):
    """Файлы /proc/sys/net/ipv4/conf/<if>/rp_filter в tmp_path; по умолчанию свободный режим."""
    monkeypatch.setattr(linux, "PROC_NET_CONF", tmp_path)

    def write(all_value: int, interface_value: int, interface: str = "eth0") -> None:
        for name, value in (("all", all_value), (interface, interface_value)):
            (tmp_path / name).mkdir(exist_ok=True)
            (tmp_path / name / "rp_filter").write_text(f"{value}\n")

    write(2, 2)
    return write


@pytest.mark.parametrize(
    ("all_value", "interface_value", "confirmed"),
    [(2, 2, True), (0, 0, True), (1, 0, False), (0, 1, False), (1, 2, True)],
)
def test_linux_strict_rp_filter_blocks_the_binding(
    monkeypatch, rp_filter, all_value, interface_value, confirmed
):
    # Действует наибольшее из all и интерфейса: 2 (свободный) перекрывает 1 (строгий).
    rp_filter(all_value, interface_value)
    route = "default via 192.0.2.1 dev eth0 metric 600\n"
    done = subprocess.CompletedProcess([], 0, stdout=route, stderr="")
    monkeypatch.setattr(linux.subprocess, "run", lambda *_a, **_k: done)

    assert linux.binding_confirmed("eth0") is confirmed


def test_linux_missing_rp_filter_counts_as_off(monkeypatch, tmp_path):
    monkeypatch.setattr(linux, "PROC_NET_CONF", tmp_path)
    route = "default via 192.0.2.1 dev eth0 metric 600\n"
    done = subprocess.CompletedProcess([], 0, stdout=route, stderr="")
    monkeypatch.setattr(linux.subprocess, "run", lambda *_a, **_k: done)

    assert linux.binding_confirmed("eth0") is True
