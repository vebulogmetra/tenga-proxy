"""Состояние службы: ядро, маршруты, DNS, откат — с подменёнными системами."""

from __future__ import annotations

import json
import threading

import pytest

from src.core.xray_manager import TrafficStats
from src.sys.windows import netinfo
from src.winsvc import wireguard
from src.winsvc.journal import Journal
from src.winsvc.state import ServiceError, ServiceState
from tests.test_sys_windows_netinfo import SNAPSHOT
from tests.test_winsvc_policy import BASE


class FakeRunner:
    def __init__(self):
        self.running = False
        self.started_with = None

    def start(self, config):
        self.started_with = config
        self.running = True
        return True, ""

    def stop(self):
        self.running = False
        return True, ""

    @property
    def is_running(self):
        return self.running

    def get_traffic(self):
        return TrafficStats(upload=5, download=7)


class FakeNet:
    def __init__(self):
        self.commands = []
        self.nrpt = []
        self.swept = False

    def run(self, cmd):
        self.commands.append(cmd)
        return True

    def nrpt_add(self, server):
        self.nrpt.append(server)
        return "{6F1D2C3B-5A7E-4E0B-9C1D-2A3B4C5D6E7F}"

    def nrpt_sweep(self):
        self.swept = True

    def undo(self, entry):
        self.commands.append(("undo", entry["op"]))

    def snapshot(self):
        return netinfo.parse_snapshot(json.dumps(SNAPSHOT))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def state(tmp_path):
    runner, net, clock = FakeRunner(), FakeNet(), Clock()
    service = ServiceState(
        runner=runner,
        net=net,
        journal=Journal(tmp_path / "j.json"),
        clock=clock,
        resolve=lambda _host: "203.0.113.7",
        adapter_wait=0,
    )
    return service, runner, net, clock


def test_hello_reports_version_mismatch(state):
    service, *_ = state

    with pytest.raises(ServiceError):
        service.hello("0.0.1-other")


def test_core_start_sanitizes_config(state):
    service, runner, *_ = state

    service.core_start(BASE)

    assert "access" not in runner.started_with["log"]


def test_routes_apply_adds_host_route_then_split_default(state):
    service, _runner, net, _clock = state

    result = service.routes_apply("xray0", "vpn.example.com")

    added = [cmd for cmd in net.commands if "add" in cmd]
    assert "prefix=203.0.113.7/32" in added[0] and "nexthop=192.168.0.1" in added[0]
    assert {"prefix=0.0.0.0/1", "prefix=128.0.0.0/1"} <= {part for cmd in added for part in cmd}
    assert result == {"proxy_ip": "203.0.113.7"}


def test_routes_apply_without_tun_adapter_fails(state):
    service, *_ = state

    with pytest.raises(ServiceError):
        service.routes_apply("missing0", "vpn.example.com")


def test_loopback_proxy_gets_no_host_route(state):
    service, _runner, net, _clock = state
    service._resolve = lambda _host: "127.0.0.1"

    service.routes_apply("xray0", "127.0.0.1")

    assert not any("prefix=127.0.0.1/32" in cmd for cmd in net.commands)


def test_dns_apply_records_nrpt_rule(state):
    service, _runner, net, _clock = state

    service.dns_apply("xray0")

    assert net.nrpt == ["1.1.1.1"]
    assert service._journal.entries()[-1]["op"] == "nrpt.remove"


def test_routes_and_dns_share_adapter_snapshot_until_rollback(state, monkeypatch):
    service, _runner, net, _clock = state
    snapshots = []
    snapshot = net.snapshot()
    monkeypatch.setattr(net, "snapshot", lambda: snapshots.append(True) or snapshot)
    service.routes_apply("xray0", "vpn.example.com")
    service.dns_apply("xray0")
    assert len(snapshots) == 1
    service.routes_restore()
    service.dns_apply("xray0")
    assert len(snapshots) == 2


def test_core_stop_rolls_everything_back(state):
    service, runner, net, _clock = state
    service.core_start(BASE)
    service.routes_apply("xray0", "vpn.example.com")
    service.dns_apply("xray0")

    service.core_stop()

    assert not runner.running
    assert service._journal.entries() == []
    assert ("undo", "nrpt.remove") in net.commands


def test_core_crash_is_noticed_by_tick(state):
    service, runner, _net, _clock = state
    service.core_start(BASE)
    service.routes_apply("xray0", "vpn.example.com")
    runner.running = False

    service.tick()

    assert service._journal.entries() == []
    status = service.core_status()
    assert status["running"] is False
    assert status["exited"] is True


def test_client_gone_stops_after_grace(state):
    service, runner, _net, clock = state
    service.core_start(BASE)
    service.client_gone()

    clock.now = 10
    service.tick()
    assert runner.running

    clock.now = 16
    service.tick()
    assert not runner.running


def test_reconnect_cancels_grace(state):
    service, runner, _net, clock = state
    service.core_start(BASE)
    service.client_gone()
    service.client_connected()

    clock.now = 100
    service.tick()

    assert runner.running


def test_startup_recovery_sweeps_nrpt_and_replays_journal(state):
    service, _runner, net, _clock = state
    service._journal.record({"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40})

    service.recover()

    assert net.swept
    assert ("undo", "route.delete") in net.commands


def test_log_lines_are_buffered_and_drained(state):
    service, *_ = state
    service.core_output("line 1")
    service.core_output("line 2")

    assert service.core_status()["log"] == ["line 1", "line 2"]
    assert service.core_status()["log"] == []


def test_stop_can_drain_core_output_without_waiting_for_state_lock(state):
    service, runner, *_ = state
    drained = threading.Event()

    def pump():
        service.core_output("last core line")
        drained.set()

    thread = threading.Thread(target=pump, daemon=True)
    completed = []

    def stop():
        thread.start()
        # XrayManager joins the output thread while core_stop holds _lock.
        completed.append(drained.wait(1))
        return True, ""

    runner.stop = stop
    service.core_stop()
    thread.join(2)
    assert completed == [True]
    assert service.core_status()["log"] == ["last core line"]


def test_stats(state):
    service, *_ = state

    assert service.core_stats() == {"upload": 5, "download": 7}


def test_wireguard_up_unknown_tunnel_is_refused(state, monkeypatch):
    service, _runner, net, _clock = state
    monkeypatch.setattr(wireguard, "list_tunnels", lambda: ["home"])

    with pytest.raises(ServiceError, match="не найден"):
        service.wireguard_up("work")
    assert net.commands == []


def test_wireguard_up_runs_wireguard_exe(state, monkeypatch):
    service, _runner, net, _clock = state
    monkeypatch.setattr(wireguard, "list_tunnels", lambda: ["home"])

    service.wireguard_up("home")

    assert net.commands == [wireguard.up_command("home")]


def test_wireguard_bad_name_runs_nothing(state):
    service, _runner, net, _clock = state

    with pytest.raises(ServiceError):
        service.wireguard_down("a;b")
    assert net.commands == []
