"""Ядро в службе и выбор между локальным и служебным запуском."""

from __future__ import annotations

from src.core.xray_manager import TrafficStats
from src.sys.windows.core_runner import ServiceCoreRunner, WindowsXrayManager
from src.winsvc.state import ServiceError

TUN = {"inbounds": [{"protocol": "tun"}]}
PROXY = {"inbounds": [{"protocol": "mixed"}]}


def ignore(_line):
    pass


class FakeClient:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def call(self, cmd, **args):
        self.calls.append(cmd)
        if self.fail == cmd:
            raise ServiceError("отказ службы")
        if cmd == "core.status":
            return {"running": True, "exited": False, "log": ["core says hi"]}
        if cmd == "core.stats":
            return {"upload": 1, "download": 2}
        return {}


class FakeLocal:
    binary_path = "C:/app/xray.exe"

    def __init__(self):
        self.running = False

    def start(self, config):
        self.running = True
        return True, ""

    def stop(self):
        self.running = False
        return True, ""

    @property
    def is_running(self):
        return self.running

    def get_traffic(self):
        return TrafficStats(9, 9)

    def get_version(self):
        return {"version": "26.9.9"}

    def set_on_stop_callback(self, callback):
        pass


def test_runner_reports_service_refusal():
    runner = ServiceCoreRunner(client=FakeClient(fail="core.start"), log_sink=ignore)

    assert runner.start(TUN) == (False, "отказ службы")


def test_runner_status_forwards_log_lines():
    lines = []
    runner = ServiceCoreRunner(client=FakeClient(), log_sink=lines.append)

    assert runner.is_running is True
    assert lines == ["core says hi"]


def test_runner_traffic():
    runner = ServiceCoreRunner(client=FakeClient(), log_sink=ignore)

    assert runner.get_traffic() == TrafficStats(1, 2)


def test_tun_config_goes_to_service():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=ignore))

    assert manager.start(TUN) == (True, "")
    assert "core.start" in client.calls
    assert not local.running


def test_proxy_config_runs_locally():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=ignore))

    manager.start(PROXY)

    assert local.running
    assert client.calls == []


def test_switching_mode_stops_previous_backend():
    client, local = FakeClient(), FakeLocal()
    manager = WindowsXrayManager(local, ServiceCoreRunner(client=client, log_sink=ignore))
    manager.start(PROXY)

    manager.start(TUN)

    assert not local.running


def test_stopped_manager_reports_nothing():
    manager = WindowsXrayManager(
        FakeLocal(), ServiceCoreRunner(client=FakeClient(), log_sink=ignore)
    )

    assert manager.is_running is False
    assert manager.get_traffic() == TrafficStats()


def test_process_alive_check_follows_active_backend():
    # ConnectionMonitor спрашивает именно _check_process_alive().
    manager = WindowsXrayManager(
        FakeLocal(), ServiceCoreRunner(client=FakeClient(), log_sink=ignore)
    )
    assert manager._check_process_alive() is False

    manager.start(PROXY)

    assert manager._check_process_alive() is True
