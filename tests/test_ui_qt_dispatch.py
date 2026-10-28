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
