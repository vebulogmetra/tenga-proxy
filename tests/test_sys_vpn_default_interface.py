"""Определение физического интерфейса для прямого выхода."""

from __future__ import annotations

import subprocess

from src.sys import vpn

ROUTES_WITH_TUN_UP = """\
default dev xray0 scope link
default via 10.8.0.1 dev tun0 proto static metric 50
default via 192.168.0.1 dev wlp1s0 proto dhcp src 192.168.0.154 metric 600
"""


def fake_ip(monkeypatch, routes: str) -> None:
    def run(cmd, **_kwargs):
        stdout = routes if cmd[:4] == ["ip", "route", "show", "default"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(vpn.subprocess, "run", run)


def test_own_tun_is_not_a_physical_interface(monkeypatch):
    """На поднятом туннеле первый маршрут по умолчанию — сам TUN приложения."""
    fake_ip(monkeypatch, ROUTES_WITH_TUN_UP)

    assert vpn.get_default_interface(exclude=("xray0",)) == "wlp1s0"


def test_without_exclusions_behaviour_is_unchanged(monkeypatch):
    fake_ip(monkeypatch, "default via 192.168.0.1 dev eth0 proto dhcp metric 100\n")

    assert vpn.get_default_interface() == "eth0"
    assert vpn.get_default_interface("eth0") is None
