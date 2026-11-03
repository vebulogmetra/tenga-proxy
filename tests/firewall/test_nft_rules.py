"""Настоящие правила nftables: от root, в отдельном сетевом пространстве.

Запуск: `make test-firewall`. Таблица общая на систему, поэтому вне отдельного
пространства тесты отказываются работать: на машине разработчика они сняли бы
блокировку живого сеанса.
"""

from __future__ import annotations

import errno
import os
import shlex
import socket
import subprocess
import time
from pathlib import Path

import pytest

from src.sys.firewall_policy import SOCKET_MARK

pytestmark = pytest.mark.firewall

HELPER = Path(__file__).resolve().parents[2] / "core/scripts/tun_route_helper.sh"
REJECTED = (errno.ECONNREFUSED, errno.EACCES, errno.EHOSTUNREACH, errno.EPERM)


def _in_own_network_namespace() -> bool:
    return os.stat("/proc/self/ns/net").st_ino != os.stat("/proc/1/ns/net").st_ino


@pytest.fixture(autouse=True)
def isolated():
    if os.environ.get("TENGA_FIREWALL_TESTS") != "1":
        pytest.skip("только через make test-firewall")
    if os.geteuid() != 0 or not _in_own_network_namespace():
        pytest.fail("нужны root и отдельное сетевое пространство: sudo unshare -n")


def run(command: str, *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(shlex.split(command), capture_output=True, text=True, check=check)


def helper(*args: str) -> None:
    subprocess.run(["sh", str(HELPER), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def lab():
    """Физический интерфейс d0 с маршрутами наружу и TUN-подобный x0."""
    run("ip link set lo up")
    run("ip link add d0 type dummy")
    run("ip link set d0 up")
    run("ip addr add 192.168.77.2/24 dev d0")
    run("ip route add default via 192.168.77.1 dev d0 metric 600")
    run("ip -6 addr add 2001:db8::2/64 dev d0 nodad")
    run("ip -6 route add default via 2001:db8::1 dev d0")
    run("ip link add x0 type dummy")
    run("ip link set x0 up")
    run("ip addr add 10.77.0.2/24 dev x0")
    yield
    run("nft delete table inet veblock", check=False)
    run("ip link del d0", check=False)
    run("ip link del x0", check=False)


def connect_errno(address: str, port: int = 443, *, mark: int | None = None) -> int:
    """0 — соединилось; ETIMEDOUT — пакет ушёл, ответа нет; иначе отказ правила."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if mark is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, mark)
        try:
            sock.connect((address, port))
        except TimeoutError:
            return errno.ETIMEDOUT
        except OSError as e:
            return e.errno or -1
    return 0


def test_ipv6_only_rejects_ipv6_at_once_and_leaves_ipv4(lab):
    helper("firewall-apply", "ipv6_only", "x0", "-", "-", "open")

    assert connect_errno("2001:db8:1::1") in REJECTED
    assert connect_errno("203.0.113.1") == errno.ETIMEDOUT


def test_rejected_tcp_over_ipv6_fails_without_waiting_for_a_retransmit(lab):
    """Клиенты без Happy Eyeballs перебирают адреса: секунда на каждый заметна."""
    helper("firewall-apply", "ipv6_only", "x0", "-", "-", "open")

    started = time.monotonic()
    assert connect_errno("2001:db8:1::1") == errno.ECONNREFUSED
    assert time.monotonic() - started < 0.2


def test_rejected_udp_fails_at_once(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(0.5)
        sock.connect(("203.0.113.1", 443))
        try:
            sock.send(b"x")
            sock.recv(10)
        except OSError as e:
            refused = e.errno
    assert refused in REJECTED


def test_ipv6_only_lets_the_cores_socket_through(lab):
    helper("firewall-apply", "ipv6_only", "x0", "-", "-", "open")

    assert connect_errno("2001:db8:1::1", mark=SOCKET_MARK) == errno.ETIMEDOUT


def test_full_rejects_direct_traffic_at_once(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    assert connect_errno("203.0.113.1") in REJECTED
    assert connect_errno("2001:db8:1::1") in REJECTED


def test_full_keeps_the_local_network(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    assert connect_errno("192.168.77.9", 22) == errno.ETIMEDOUT


def test_full_lets_marked_sockets_and_the_tunnel_through(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    assert connect_errno("203.0.113.1", mark=SOCKET_MARK) == errno.ETIMEDOUT
    assert connect_errno("10.77.0.9") == errno.ETIMEDOUT


def test_another_mark_is_not_enough(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    assert connect_errno("203.0.113.1", mark=SOCKET_MARK + 1) in REJECTED


def test_closed_dns_blocks_the_router_and_open_dns_does_not(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "open")
    assert connect_errno("192.168.77.1", 53) == errno.ETIMEDOUT

    helper("firewall-apply", "full", "x0", "-", "-", "closed")
    assert connect_errno("192.168.77.1", 53) in REJECTED


def test_vpn_server_address_stays_reachable(lab):
    helper("firewall-apply", "full", "x0", "-", "203.0.113.5,2001:db8:5::5", "closed")

    assert connect_errno("203.0.113.5") == errno.ETIMEDOUT
    assert connect_errno("2001:db8:5::5") == errno.ETIMEDOUT
    assert connect_errno("203.0.113.6") in REJECTED


def test_reapply_replaces_the_rules_instead_of_adding(lab):
    helper("firewall-apply", "full", "x0", "-", "-", "open")
    helper("firewall-apply", "full", "x0", "-", "-", "closed")

    table = run("nft list table inet veblock").stdout
    assert table.count("chain output") == 1
    assert table.count("dport 53") == 4  # tcp и udp в output и forward
    assert "nft delete table inet veblock" in table


def test_remove_is_idempotent(lab):
    helper("firewall-apply", "ipv6_only", "x0", "-", "-", "open")

    helper("firewall-remove")
    helper("firewall-remove")

    assert "veblock" not in run("nft list ruleset").stdout
    assert connect_errno("2001:db8:1::1") == errno.ETIMEDOUT
