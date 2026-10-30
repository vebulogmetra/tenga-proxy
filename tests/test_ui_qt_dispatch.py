"""QtLoop: доставка в главный поток и таймеры поверх Qt."""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from src.ui.qt.dispatch import QtLoop
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


def test_dispatch_from_a_worker_runs_on_the_main_thread(qapp):
    loop = QtLoop()
    seen = []

    worker = threading.Thread(
        target=lambda: loop.dispatch(lambda x: seen.append((x, threading.current_thread())), 1)
    )
    worker.start()
    worker.join()
    assert seen == []

    wait_until(lambda: seen)
    assert seen == [(1, threading.main_thread())]


def test_dispatch_ignores_the_return_value(qapp):
    loop = QtLoop()
    calls = []

    loop.dispatch(lambda: calls.append(1) or True)
    wait_until(lambda: calls)
    for _ in range(5):
        process_events()

    assert calls == [1]


def test_schedule_repeats_while_the_callback_returns_true(qapp):
    loop = QtLoop()
    ticks = []

    loop.schedule(5, lambda: ticks.append(1) or len(ticks) < 3)

    wait_until(lambda: len(ticks) == 3)
    for _ in range(10):
        process_events()
    assert len(ticks) == 3


def test_cancel_stops_the_timer(qapp):
    loop = QtLoop()
    ticks = []
    handle = loop.schedule(5, lambda: ticks.append(1) or True)

    loop.cancel(handle)
    loop.cancel(handle)  # повторная отмена не ошибка
    for _ in range(10):
        process_events()

    assert ticks == []


def test_monitor_runs_on_the_qt_loop(qapp, tmp_path):
    from src.core.context import AppContext
    from src.core.monitor import ConnectionMonitor

    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    loop = QtLoop()
    monitor = ConnectionMonitor(context, loop=loop)
    monitor._check_connections = lambda: True

    monitor.start()
    assert len(loop._timers) == 2
    monitor.stop()

    assert loop._timers == set()


def test_monitor_started_in_worker_updates_traffic(qapp, tmp_path):
    from types import SimpleNamespace

    from src.core.context import AppContext
    from src.core.monitor import ConnectionMonitor
    from src.core.xray_manager import TrafficStats

    context = AppContext(config_dir=tmp_path)
    context.config.monitoring.enabled = True
    context.config.traffic_loop_interval = 200
    context._xray_manager = SimpleNamespace(
        get_traffic=lambda: TrafficStats(upload=4096, download=8192)
    )
    context.proxy_state.set_running(profile_id=1)
    loop = QtLoop()
    monitor = ConnectionMonitor(context, loop=loop)
    monitor._check_connections = lambda: True
    threads = []
    context.proxy_state.add_listener(lambda _state: threads.append(threading.current_thread()))
    worker = threading.Thread(target=monitor.start)
    worker.start()
    worker.join()
    try:
        wait_until(lambda: context.proxy_state.download_bytes == 8192)
        assert context.proxy_state.upload_bytes == 4096
        assert threads == [threading.main_thread()]
        assert all(timer.thread() == loop.thread() for timer in loop._timers)
    finally:
        worker = threading.Thread(target=monitor.stop)
        worker.start()
        worker.join()
        wait_until(lambda: not loop._timers)


def test_worker_can_cancel_timer_before_creation(qapp):
    loop = QtLoop()
    ticks = []

    def worker_task():
        handle = loop.schedule(1, lambda: ticks.append(1) or True)
        loop.cancel(handle)
        loop.cancel(handle)

    worker = threading.Thread(target=worker_task)
    worker.start()
    worker.join()
    for _ in range(10):
        process_events()
    assert not ticks
    assert not loop._timers
