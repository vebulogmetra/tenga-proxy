"""Адреса DNS VPN и bootstrap-имена прокси проверяются как IP, а не по первой цифре."""

from __future__ import annotations

import pytest

from src.core.dns_config import build_dns, parse_dns_endpoint
from src.db.config import DnsSettings


@pytest.mark.parametrize(
    "endpoint",
    ["999.1.1.1", "10.1.2.3:99999", "10.1.2.3:0", "10.1.2.3:-1"],
)
def test_invalid_dns_ip_or_port_is_rejected(endpoint):
    assert parse_dns_endpoint(endpoint) is None


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("10.1.2.3", ("10.1.2.3", 53)),
        ("IP4.DNS[1]:10.1.2.3:5353", ("10.1.2.3", 5353)),
        ("10.1.2.3:65535", ("10.1.2.3", 65535)),
    ],
)
def test_valid_dns_endpoints_keep_the_address_and_port(endpoint, expected):
    assert parse_dns_endpoint(endpoint) == expected


def test_a_proxy_domain_starting_with_a_digit_gets_bootstrap_dns():
    config = build_dns(DnsSettings(), proxy_host="1proxy.example")
    bootstrap = [server for server in config["servers"] if isinstance(server, dict)]
    assert any(server.get("domains") == ["full:1proxy.example"] for server in bootstrap)


@pytest.mark.parametrize("address", ["203.0.113.7", "abcd::1", "::1", "2001:db8::1"])
def test_an_ip_proxy_address_needs_no_bootstrap_domain_rule(address):
    config = build_dns(DnsSettings(), proxy_host=address)
    assert not any(
        isinstance(server, dict) and server.get("domains") == [f"full:{address}"]
        for server in config["servers"]
    )
