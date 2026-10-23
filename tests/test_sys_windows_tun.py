"""Маршруты и DNS TUN на Windows — вызовы службы."""

from __future__ import annotations

import pytest

from src.sys.windows import service_client, tun_dns, tun_route
from src.winsvc.state import ServiceError


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, cmd, **args):
        self.calls.append((cmd, args))
        if cmd == self.fail:
            raise ServiceError("нет адаптера")
        return {"proxy_ip": "203.0.113.7"} if cmd == "routes.apply" else {}


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(service_client, "get_client", lambda: fake)
    return fake


def test_apply_returns_state(client):
    ok, state, error = tun_route.apply_tun_routes("xray0", "vpn.example.com")

    assert (ok, error) == (True, "")
    assert state == tun_route.TunRouteState(tun_name="xray0", proxy_ip="203.0.113.7")
    assert client.calls == [
        ("routes.apply", {"tun_name": "xray0", "proxy_host": "vpn.example.com"})
    ]


def test_apply_failure_text_reaches_ui(client):
    client.fail = "routes.apply"

    assert tun_route.apply_tun_routes("xray0", "h") == (False, None, "нет адаптера")


def test_restore_calls_service(client):
    assert tun_route.restore_tun_routes(tun_route.TunRouteState("xray0", "1.2.3.4")) == (True, "")
    assert client.calls[-1][0] == "routes.restore"


def test_restore_nothing_is_fine(client):
    assert tun_route.restore_tun_routes(None) == (True, "")
    assert client.calls == []


def test_dns(client):
    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert client.calls == [("dns.apply", {"tun_name": "xray0"})]
