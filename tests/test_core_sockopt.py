"""Опции сокетов outbound'ов, общие для рабочего и пробного ядра."""

from __future__ import annotations

import pytest

from src.core.sockopt import (
    bind_to_interface,
    is_ip,
    is_loopback,
    mark_socket,
    resolve_in_core,
)


def test_bind_creates_stream_settings_and_keeps_other_options():
    outbound = {"protocol": "freedom", "streamSettings": {"sockopt": {"tcpFastOpen": True}}}

    bind_to_interface(outbound, "eth0")
    mark_socket(outbound, 0x7E6A)
    resolve_in_core(outbound)

    assert outbound["streamSettings"]["sockopt"] == {
        "tcpFastOpen": True,
        "interface": "eth0",
        "mark": 0x7E6A,
        "domainStrategy": "UseIPv4",
    }


def test_bind_without_stream_settings():
    outbound = {"protocol": "freedom"}
    bind_to_interface(outbound, "eth0")
    assert outbound["streamSettings"] == {"sockopt": {"interface": "eth0"}}


@pytest.mark.parametrize(
    ("host", "loopback", "ip"),
    [
        ("localhost", True, False),
        ("127.0.0.1", True, True),
        ("::1", True, True),
        ("203.0.113.5", False, True),
        ("[2001:db8::1]", False, True),
        ("srv.example.com", False, False),
    ],
)
def test_loopback_and_ip_detection(host, loopback, ip):
    assert is_loopback(host) is loopback
    assert is_ip(host) is ip
