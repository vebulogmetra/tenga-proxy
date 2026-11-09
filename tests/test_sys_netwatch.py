"""Отпечаток сети: маршрут по умолчанию мимо TUN на Linux и Windows."""

from __future__ import annotations

import json

from src.sys.linux import netwatch as linux_netwatch
from src.sys.windows import netinfo
from src.sys.windows import netwatch as windows_netwatch

ROUTES = """\
default via 192.168.1.1 dev wlp2s0 proto dhcp src 192.168.1.20 metric 600
default via 10.0.0.1 dev enp3s0 proto dhcp metric 100
default dev xray0 scope link
"""


def test_linux_picks_the_lowest_metric_outside_the_tunnel():
    assert linux_netwatch.parse_default_route(ROUTES, exclude=["xray0"]) == (
        "10.0.0.1",
        "enp3s0",
    )


def test_linux_route_without_a_gateway_keeps_the_interface():
    assert linux_netwatch.parse_default_route("default dev ppp0 scope link\n") == ("", "ppp0")


def test_linux_without_a_default_route():
    assert linux_netwatch.parse_default_route("", exclude=()) is None
    assert linux_netwatch.parse_default_route("default dev xray0\n", exclude=["xray0"]) is None


def test_linux_default_route_reads_ip(monkeypatch):
    class Done:
        returncode = 0
        stdout = ROUTES

    monkeypatch.setattr(linux_netwatch.subprocess, "run", lambda *_a, **_k: Done())
    monkeypatch.setattr(linux_netwatch, "_tun_devices", lambda: ["xray0"])

    assert linux_netwatch.default_route() == ("10.0.0.1", "enp3s0")


def test_linux_default_route_survives_a_missing_ip(monkeypatch):
    def missing(*_a, **_k):
        raise FileNotFoundError("ip")

    monkeypatch.setattr(linux_netwatch.subprocess, "run", missing)

    assert linux_netwatch.default_route() is None


SNAPSHOT = {
    "adapters": [
        {"alias": "Wi-Fi", "index": 12, "status": "Up", "description": "Intel(R) Wi-Fi 6"},
        {"alias": "xray0", "index": 40, "status": "Up", "description": "Wintun Userspace Tunnel"},
    ],
    "ips": [],
    "dns": [],
    "routes": [
        {"alias": "xray0", "index": 40, "nexthop": "0.0.0.0", "metric": 0, "ifmetric": 5},
        {"alias": "Wi-Fi", "index": 12, "nexthop": "192.168.0.1", "metric": 0, "ifmetric": 25},
    ],
}


def test_windows_takes_a_fresh_snapshot_and_skips_the_tunnel(monkeypatch):
    calls = []
    monkeypatch.setattr(netinfo, "invalidate", lambda: calls.append("invalidate"))
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.parse_snapshot(json.dumps(SNAPSHOT)))

    assert windows_netwatch.default_route() == ("192.168.0.1", "Wi-Fi")
    assert calls == ["invalidate"]


def test_windows_without_a_physical_route(monkeypatch):
    monkeypatch.setattr(netinfo, "invalidate", lambda: None)
    monkeypatch.setattr(netinfo, "snapshot", lambda: netinfo.NetSnapshot())

    assert windows_netwatch.default_route() is None
