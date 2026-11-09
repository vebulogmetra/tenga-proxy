from __future__ import annotations

import json
import os
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from src.core.xray_manager import TrafficStats, XrayManager


def _answering(monkeypatch, stdout: str, returncode: int = 0) -> None:
    """Make the stats call return this text instead of running the core."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, returncode, stdout=stdout, stderr=""
        ),
    )


def _make_manager(monkeypatch) -> XrayManager:
    """Manager that never touches the real binary.

    Конструктор спрашивает у ядра версию, запуская процесс: тестам это не
    нужно и в среде без бинарника только мешает.
    """
    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    return XrayManager(binary_path="/nonexistent")


def test_inject_stats_api_enables_the_outbound_counters(monkeypatch):
    """Без policy ядро не считает трафик, сколько ни включай stats."""
    manager = _make_manager(monkeypatch)
    config = manager._inject_stats_api({"inbounds": [], "outbounds": []})

    system = config["policy"]["system"]
    assert system["statsOutboundUplink"] is True
    assert system["statsOutboundDownlink"] is True


def test_inject_stats_api_keeps_an_existing_policy(monkeypatch):
    """Своя policy пользователя не затирается, счётчики к ней добавляются."""
    manager = _make_manager(monkeypatch)
    config = manager._inject_stats_api({"policy": {"levels": {"0": {"handshake": 4}}}})

    assert config["policy"]["levels"] == {"0": {"handshake": 4}}
    assert config["policy"]["system"]["statsOutboundUplink"] is True


def test_inject_stats_api_leaves_the_original_config_alone(monkeypatch):
    """Аргумент не правится на месте: копия словаря поверхностная."""
    manager = _make_manager(monkeypatch)
    original = {"policy": {"system": {"statsInboundUplink": True}}}

    manager._inject_stats_api(original)

    assert original["policy"]["system"] == {"statsInboundUplink": True}


_STATS_ANSWER = """
{
    "stat": [
        {"name": "outbound>>>proxy>>>traffic>>>uplink", "value": 1024},
        {"name": "outbound>>>proxy>>>traffic>>>downlink", "value": 2048},
        {"name": "outbound>>>api>>>traffic>>>uplink"}
    ]
}
"""


def test_get_traffic_reads_the_counters(monkeypatch):
    """Цифры берутся из ответа ядра, а не выдумываются нулями."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, _STATS_ANSWER)

    stats = manager.get_traffic()

    assert stats.upload == 1024
    assert stats.download == 2048


def test_get_traffic_asks_the_core_for_stats(monkeypatch):
    """Опрос идёт вызовом statsquery у того же бинарника."""
    manager = _make_manager(monkeypatch)
    seen: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=_STATS_ANSWER, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    manager.get_traffic()

    assert seen, "статистику обязаны были спросить у ядра"
    command = seen[0]
    assert command[0] == "/nonexistent"
    assert command[1:3] == ["api", "statsquery"]
    assert any(part.startswith("--server=") for part in command)


def test_get_traffic_counts_a_missing_value_as_zero(monkeypatch):
    """Обнулённый счётчик приходит без ключа value, а не с нулём в нём."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, '{"stat": [{"name": "outbound>>>proxy>>>traffic>>>uplink"}]}')

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_dead_core(monkeypatch):
    """Опрос идёт по таймеру: упасть при остановленном ядре он не вправе."""
    manager = _make_manager(monkeypatch)

    def explode(*_args, **_kwargs):
        raise OSError("нет такого файла")

    monkeypatch.setattr(subprocess, "run", explode)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_timeout(monkeypatch):
    """Зависший вызов гасится таймаутом и не роняет опрос."""
    manager = _make_manager(monkeypatch)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="xray", timeout=5)

    monkeypatch.setattr(subprocess, "run", timeout)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_broken_output(monkeypatch):
    """Ответ не по формату — это нули, а не исключение."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, "не json")

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_failing_call(monkeypatch):
    """Ненулевой код возврата означает, что спрашивать нечего."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, "", returncode=1)

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_sums_the_proxy_outbounds(monkeypatch):
    """Тег outbound — имя профиля; служебные каналы в счёт не идут."""
    manager = _make_manager(monkeypatch)
    profile = "🇵🇱Польша | XHTTP VPN#6"
    _answering(
        monkeypatch,
        json.dumps(
            {
                "stat": [
                    {"name": f"outbound>>>{profile}>>>traffic>>>uplink", "value": 500},
                    {"name": f"outbound>>>{profile}>>>traffic>>>downlink", "value": 900},
                    {"name": "outbound>>>direct>>>traffic>>>uplink", "value": 111},
                    {"name": "outbound>>>vpn>>>traffic>>>downlink", "value": 222},
                    {"name": "outbound>>>api>>>traffic>>>uplink", "value": 333},
                    {"name": "outbound>>>main-dns>>>traffic>>>downlink", "value": 444},
                    {"name": "outbound>>>local-dns>>>traffic>>>uplink", "value": 555},
                    {"name": "outbound>>>vpn-dns>>>traffic>>>downlink", "value": 666},
                    {"name": "inbound>>>tun-in>>>traffic>>>uplink", "value": 777},
                ]
            }
        ),
    )

    assert manager.get_traffic() == TrafficStats(upload=500, download=900)


def test_get_traffic_still_counts_an_unnamed_profile(monkeypatch):
    """У безымянного профиля тегом остаётся proxy: он тоже трафик прокси."""
    manager = _make_manager(monkeypatch)
    _answering(monkeypatch, _STATS_ANSWER)

    assert manager.get_traffic() == TrafficStats(upload=1024, download=2048)


def test_get_traffic_ignores_a_malformed_counter_name(monkeypatch):
    """Имя не из четырёх частей пропускается, а не роняет разбор."""
    manager = _make_manager(monkeypatch)
    _answering(
        monkeypatch,
        json.dumps(
            {
                "stat": [
                    {"name": "outbound>>>node>>>uplink", "value": 10},
                    {"name": "странное имя", "value": 20},
                    {"name": "outbound>>>node>>>traffic>>>uplink", "value": 30},
                ]
            }
        ),
    )

    assert manager.get_traffic() == TrafficStats(upload=30, download=0)


def test_core_is_started_without_console_window(monkeypatch, tmp_path):
    import io

    from src.core import platform_info, xray_manager

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)
            self.stdout = io.BytesIO(b"")
            self.pid = 1

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(xray_manager.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(XrayManager, "_core_logger", lambda _self: xray_manager.logger)
    monkeypatch.setattr(XrayManager, "_wait_for_process_ready", lambda _self, **_kwargs: True)
    manager = _make_manager(monkeypatch)
    monkeypatch.setattr(manager, "_binary_path", str(tmp_path / "xray"))

    ok, _error = manager.start({"inbounds": [], "outbounds": []})

    assert ok
    assert seen["creationflags"] == platform_info.CREATE_NO_WINDOW


def test_stats_query_runs_without_console_window(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
    seen = {}

    def fake_run(*args, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout='{"stat": []}', stderr="")

    manager = _make_manager(monkeypatch)
    monkeypatch.setattr(subprocess, "run", fake_run)

    manager.get_traffic()

    assert seen.get("creationflags") == platform_info.CREATE_NO_WINDOW


class _FakeCore:
    """Процесс ядра: stdout — настоящий pipe, конец вывода приходит при смерти."""

    pid = 4242

    def __init__(self) -> None:
        read_end, write_end = os.pipe()
        self.stdout = os.fdopen(read_end, "rb")
        self._write_end = os.fdopen(write_end, "wb")
        self.returncode = None

    def poll(self):
        return self.returncode

    def die(self, code: int = 1) -> None:
        self.returncode = code
        self._write_end.close()

    def terminate(self) -> None:
        if self.returncode is None:
            self.die(0)

    def wait(self, timeout=None):
        return self.returncode


def _start_with(monkeypatch, manager, process, ready=True):
    monkeypatch.setattr("src.core.xray_manager.subprocess.Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(manager, "_wait_for_process_ready", lambda **_k: ready)
    monkeypatch.setattr(manager, "_core_logger", lambda: MagicMock())
    return manager.start({"inbounds": [], "outbounds": []})


def _watched_manager(monkeypatch):
    manager = _make_manager(monkeypatch)
    fired = threading.Event()
    manager.set_on_unexpected_exit(fired.set)
    return manager, fired


def test_core_death_after_a_successful_start_is_reported(monkeypatch):
    manager, fired = _watched_manager(monkeypatch)
    core = _FakeCore()

    ok, _ = _start_with(monkeypatch, manager, core)
    assert ok
    assert not fired.is_set()

    core.die()

    assert fired.wait(1.0)


def test_exit_during_startup_is_not_an_unexpected_exit(monkeypatch):
    """Ядро, упавшее в окне готовности, — ошибка start(), а не обрыв."""
    manager, fired = _watched_manager(monkeypatch)
    core = _FakeCore()
    core.die()

    ok, _ = _start_with(monkeypatch, manager, core, ready=False)

    assert not ok
    assert not fired.wait(0.2)


def test_exit_right_after_the_ready_window_fails_the_start_without_a_report(monkeypatch):
    """Ядро умерло на границе окна: start() и сигнал не должны сработать оба."""
    manager, fired = _watched_manager(monkeypatch)
    core = _FakeCore()
    core.die()

    ok, error = _start_with(monkeypatch, manager, core, ready=True)

    assert not ok
    assert "exited" in error
    assert not fired.wait(0.2)


def test_requested_stop_is_not_an_unexpected_exit(monkeypatch):
    manager, fired = _watched_manager(monkeypatch)
    assert _start_with(monkeypatch, manager, _FakeCore())[0]

    manager.stop()

    assert not fired.wait(0.2)


def test_failing_callback_does_not_escape_the_pump(monkeypatch):
    manager = _make_manager(monkeypatch)
    called = threading.Event()

    def explode():
        called.set()
        raise RuntimeError("boom")

    manager.set_on_unexpected_exit(explode)
    core = _FakeCore()
    assert _start_with(monkeypatch, manager, core)[0]

    core.die()

    assert called.wait(1.0)


def test_readiness_probe_returns_without_fixed_delay(monkeypatch):
    manager = _make_manager(monkeypatch)
    manager._process = MagicMock()
    manager._process.poll.return_value = None
    monkeypatch.setattr(
        "src.core.xray_manager.time.sleep", lambda *_: pytest.fail("unexpected sleep")
    )
    assert manager._wait_for_process_ready(ready=lambda: True)


def test_readiness_timeout_does_not_report_live_unready_core_as_ready(monkeypatch):
    manager = _make_manager(monkeypatch)
    manager._process = MagicMock()
    manager._process.poll.return_value = None
    assert not manager._wait_for_process_ready(timeout=0, ready=lambda: False)


def test_dead_core_is_not_ready_even_when_probe_succeeds(monkeypatch):
    manager = _make_manager(monkeypatch)
    manager._process = MagicMock()
    manager._process.poll.return_value = 1
    assert not manager._wait_for_process_ready(ready=lambda: True)


def test_readiness_probe_error_stops_the_started_core(monkeypatch):
    manager = _make_manager(monkeypatch)
    core = _FakeCore()

    def fail(_config):
        raise OSError("adapter query failed")

    manager._startup_ready = fail
    monkeypatch.setattr(manager._stats_endpoint, "is_ready", lambda: True)
    monkeypatch.setattr("src.core.xray_manager.subprocess.Popen", lambda *_a, **_k: core)
    monkeypatch.setattr(manager, "_core_logger", lambda: MagicMock())
    ok, error = manager.start({"inbounds": [], "outbounds": []})
    assert not ok and "adapter query failed" in error
    assert core.poll() is not None
    assert manager._process is None
