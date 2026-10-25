import json

import pytest

import src.sys.linux.tun_route as tun_route
from src.sys.linux.tun_route import _parse_default_route, _resolve_ipv4


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


# --- журнал отката ---

DEFAULT_WIFI = "default via 192.168.0.1 dev wlp1s0 proto dhcp metric 600"


class FakeSystem:
    """`ip` и помощник без настоящей системы: таблица — одна строка default."""

    def __init__(self, default: str = DEFAULT_WIFI, *, fail_apply=False, fail_restore=False):
        self.default = default
        self.fail_apply = fail_apply
        self.fail_restore = fail_restore
        self.calls: list[tuple] = []
        self.journal_on_apply: list[dict] | None = None

    def run_command(self, cmd, timeout=10):
        self.calls.append(("cmd", cmd))
        if cmd[:4] == ["ip", "route", "show", "default"]:
            return True, self.default, ""
        return True, "", ""

    def run_helper(self, action, args, timeout=15):
        self.calls.append(("helper", action, args))
        if action == "apply":
            self.journal_on_apply = tun_route._journal().entries()
            if self.fail_apply:
                return False, "denied"
            self.default = f"default dev {args[0]} scope link"
        if action == "restore":
            if self.fail_restore:
                return False, "denied"
            gateway, dev = args[1], args[2]
            self.default = f"default via {gateway} dev {dev}"
        return True, ""

    def run_batch(self, commands, timeout=20):
        self.calls.append(("batch", commands))
        return False, "denied"

    def restores(self):
        return [call for call in self.calls if call[:2] == ("helper", "restore")]


@pytest.fixture
def system(monkeypatch, tmp_path):
    fake = FakeSystem()
    monkeypatch.setattr(tun_route, "JOURNAL_FILE", tmp_path / "tun-route-journal.json")
    monkeypatch.setattr(tun_route, "_run_command", fake.run_command)
    monkeypatch.setattr(tun_route, "_run_helper", fake.run_helper)
    monkeypatch.setattr(tun_route, "_run_ip_batch_privileged", fake.run_batch)
    return fake


def test_apply_records_the_route_to_restore_before_changing_it(system):
    ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert ok
    assert system.journal_on_apply == [
        {
            "op": "route.restore",
            "tun_name": "xray0",
            "proxy_ip": "8.8.8.8",
            "gateway": "192.168.0.1",
            "dev": "wlp1s0",
            "metric": "600",
        }
    ]
    assert tun_route._journal().entries() == system.journal_on_apply
    assert state.default_dev == "wlp1s0"


def test_failed_apply_leaves_no_journal(system):
    system.fail_apply = True

    ok, _state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert not ok
    assert tun_route._journal().entries() == []


def test_restore_clears_the_journal(system):
    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert tun_route.restore_tun_routes(state) == (True, "")
    assert tun_route._journal().entries() == []


def test_failed_restore_keeps_the_journal_for_next_start(system):
    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.fail_restore = True

    ok, _ = tun_route.restore_tun_routes(state)

    assert not ok
    assert len(tun_route._journal().entries()) == 1


def test_recover_without_journal_touches_nothing(system):
    assert tun_route.recover_tun_routes() == (True, "")
    assert system.calls == []


def test_recover_restores_default_route_left_by_a_crash(system):
    tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.calls.clear()

    assert tun_route.recover_tun_routes() == (True, "")

    assert system.restores() == [("helper", "restore", ["8.8.8.8", "192.168.0.1", "wlp1s0", "600"])]
    assert tun_route._journal().entries() == []


def test_recover_restores_when_tun_vanished_with_the_default_route(system):
    tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.default = ""

    tun_route.recover_tun_routes()

    assert len(system.restores()) == 1


def test_recover_skips_a_system_that_already_has_its_own_default(system):
    # После перезагрузки маршрут по умолчанию уже другой: старый не возвращаем.
    tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.default = "default via 10.0.0.1 dev enp3s0"

    assert tun_route.recover_tun_routes() == (True, "")

    assert system.restores() == []
    assert tun_route._journal().entries() == []


def test_recover_keeps_journal_when_restore_fails(system):
    tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.fail_restore = True

    ok, _ = tun_route.recover_tun_routes()

    assert not ok
    assert len(tun_route._journal().entries()) == 1


@pytest.mark.parametrize(
    "entry",
    [
        {"op": "shell", "cmd": "reboot"},
        {
            "op": "route.restore",
            "tun_name": "xray0",
            "proxy_ip": "8.8.8.8",
            "gateway": "1.1.1.1; rm -rf /",
            "dev": "eth0",
            "metric": None,
        },
        {
            "op": "route.restore",
            "tun_name": "xray0",
            "proxy_ip": "8.8.8.8",
            "gateway": None,
            "dev": "eth0 table 5",
            "metric": None,
        },
        {
            "op": "route.restore",
            "tun_name": "xray0",
            "proxy_ip": "8.8.8.8",
            "gateway": None,
            "dev": "eth0",
            "metric": "6 0",
        },
    ],
)
def test_journal_rejects_entries_outside_the_schema(system, entry):
    tun_route.JOURNAL_FILE.write_text(json.dumps([entry]))

    assert tun_route._journal().entries() == []


def test_reconnect_after_failed_restore_keeps_the_original_route(system):
    # Откат не удался — маршрут по умолчанию всё ещё в TUN. Новое подключение
    # не должно принять его за исходный: иначе вернуть будет нечего.
    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")
    system.fail_restore = True
    tun_route.restore_tun_routes(state)
    system.fail_restore = False

    _ok, state, _ = tun_route.apply_tun_routes("xray0", "8.8.8.8")

    assert (state.default_gateway, state.default_dev) == ("192.168.0.1", "wlp1s0")
    assert tun_route._journal().entries()[-1]["dev"] == "wlp1s0"
