import src.sys.tun_route as tun_route
from src.sys.tun_route import _parse_default_route, _resolve_ipv4


def test_parse_default_route_with_gateway_and_metric():
    line = "default via 192.168.0.1 dev wlp1s0 proto dhcp src 192.168.0.154 metric 600"
    gateway, dev, metric = _parse_default_route(line)
    assert gateway == "192.168.0.1"
    assert dev == "wlp1s0"
    assert metric == "600"


def test_parse_default_route_without_gateway():
    line = "default dev xray0 scope link"
    gateway, dev, metric = _parse_default_route(line)
    assert gateway is None
    assert dev == "xray0"
    assert metric is None


def test_resolve_ipv4_accepts_valid_literal():
    assert _resolve_ipv4("8.8.8.8") == "8.8.8.8"


def test_resolve_ipv4_rejects_invalid_literal():
    assert _resolve_ipv4("999.999.999.999") is None


def test_run_helper_uses_non_interactive_sudo(monkeypatch):
    calls: list[list[str]] = []

    def fake_run_command(cmd: list[str], timeout: int = 15):
        calls.append(cmd)
        return False, "", "denied"

    monkeypatch.setattr(tun_route.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(
        tun_route.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None
    )
    monkeypatch.setattr(tun_route, "_run_command", fake_run_command)

    tun_route._run_helper("restore", ["1.1.1.1", "-", "eth0", "-"])
    assert calls
    assert calls[0][:2] == ["sudo", "-n"]


def test_run_ip_batch_fallback_uses_non_interactive_sudo(monkeypatch):
    calls: list[list[str]] = []

    def fake_run_command(cmd: list[str], timeout: int = 20):
        calls.append(cmd)
        if cmd and cmd[0] == "ip":
            return False, "", "op not permitted"
        if cmd[:2] == ["sudo", "-n"]:
            return True, "", ""
        return False, "", "unexpected command"

    monkeypatch.setattr(
        tun_route.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None
    )
    monkeypatch.setattr(tun_route, "_run_command", fake_run_command)

    ok, err = tun_route._run_ip_batch_privileged([["route", "replace", "default", "dev", "xray0"]])
    assert ok is True
    assert err == ""
    assert any(cmd[:2] == ["sudo", "-n"] for cmd in calls)
