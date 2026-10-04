from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from src.ui.logic.latency import LatencyRunner, make_batch_probe


def _collect(results: dict, done: list):
    def on_result(profile_id: int, latency_ms: int) -> None:
        results[profile_id] = latency_ms

    def on_done() -> None:
        done.append(True)

    return on_result, on_done


def test_runner_limits_concurrency_and_reports_every_profile():
    active = 0
    peak = 0
    lock = threading.Lock()

    def probe(profile_id: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return profile_id * 10

    delivered: list = []
    runner = LatencyRunner(probe, max_workers=2, dispatch=lambda fn, *a: delivered.append((fn, a)))
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([1, 2, 3, 4, 5], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}
    assert done == [True]
    assert peak <= 2
    assert runner.is_busy is False


def test_runner_reports_minus_one_when_probe_raises():
    def probe(profile_id: int) -> int:
        raise RuntimeError("boom")

    delivered: list = []
    runner = LatencyRunner(probe, max_workers=1, dispatch=lambda fn, *a: delivered.append((fn, a)))
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([7], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {7: -1}
    assert done == [True]


def test_runner_rejects_second_run_while_busy():
    started = threading.Event()
    release = threading.Event()

    def probe(profile_id: int) -> int:
        started.set()
        release.wait(2)
        return 1

    runner = LatencyRunner(probe, max_workers=1, dispatch=lambda *_: None)
    assert runner.run([1], on_result=lambda *_: None, on_done=lambda: None) is True
    started.wait(1)
    assert runner.run([2], on_result=lambda *_: None, on_done=lambda: None) is False
    release.set()
    runner.wait(timeout=5)


def test_runner_stays_busy_until_on_done_is_delivered():
    """Ставится ли новый запуск в очередь, пока on_done прошлого ещё не доставлен."""
    delivered: list = []
    runner = LatencyRunner(
        lambda profile_id: profile_id,
        max_workers=1,
        dispatch=lambda fn, *a: delivered.append((fn, a)),
    )

    order: list = []
    runner.run(
        [1],
        on_result=lambda p, _latency: order.append(("result", p)),
        on_done=lambda: order.append(("done", 1)),
    )
    runner.wait(timeout=5)

    # Воркер закончил, но очередь ещё не разобрана: второй запуск недопустим.
    assert runner.is_busy is True
    assert runner.run([2], on_result=lambda *_: None, on_done=lambda: None) is False

    for fn, args in delivered:
        fn(*args)

    assert order == [("result", 1), ("done", 1)]
    assert runner.is_busy is False
    assert runner.run([2], on_result=lambda *_: None, on_done=lambda: None) is True
    runner.wait(timeout=5)


def test_runner_delivers_every_result_when_probe_raises_base_exception():
    """KeyboardInterrupt в пробе не должен обрывать доставку остальных."""

    def probe(profile_id: int) -> int:
        if profile_id == 2:
            raise KeyboardInterrupt("прерывание")
        return profile_id * 10

    delivered: list = []
    runner = LatencyRunner(probe, max_workers=1, dispatch=lambda fn, *a: delivered.append((fn, a)))
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([1, 2, 3, 4, 5], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {1: 10, 2: -1, 3: 30, 4: 40, 5: 50}
    assert done == [True]


# --- пакетный режим: один вызов на весь набор ---


def test_batch_runner_hands_every_id_to_one_probe_call_and_streams_results():
    calls: list[list[int]] = []

    def batch_probe(profile_ids, emit) -> None:
        calls.append(list(profile_ids))
        for profile_id in reversed(profile_ids):
            emit(profile_id, profile_id * 10)

    delivered: list = []
    runner = LatencyRunner(batch_probe=batch_probe, dispatch=lambda _fn, *a: delivered.append(a))

    runner.run([1, 2, 3], on_result=lambda *_: None, on_done=lambda: None)
    runner.wait(timeout=5)

    assert calls == [[1, 2, 3]]
    # Результаты уходят в том порядке, в каком их отдал замер; последним — on_done.
    assert delivered[:3] == [(3, 30), (2, 20), (1, 10)]
    assert len(delivered) == 4


def test_batch_runner_reports_minus_one_for_everything_the_probe_left_out():
    def batch_probe(profile_ids, emit) -> None:
        emit(1, 10)
        raise RuntimeError("ядро не запустилось")

    delivered: list = []
    runner = LatencyRunner(
        batch_probe=batch_probe, dispatch=lambda fn, *a: delivered.append((fn, a))
    )
    results: dict = {}
    done: list = []
    on_result, on_done = _collect(results, done)

    runner.run([1, 2, 3], on_result=on_result, on_done=on_done)
    runner.wait(timeout=5)
    for fn, args in delivered:
        fn(*args)

    assert results == {1: 10, 2: -1, 3: -1}
    assert done == [True]
    assert runner.is_busy is False


def test_batch_runner_ignores_a_second_result_for_the_same_profile():
    def batch_probe(profile_ids, emit) -> None:
        emit(1, 10)
        emit(1, 99)

    delivered: list = []
    runner = LatencyRunner(batch_probe=batch_probe, dispatch=lambda _fn, *a: delivered.append(a))

    runner.run([1], on_result=lambda *_: None, on_done=lambda: None)
    runner.wait(timeout=5)

    assert delivered[0] == (1, 10)
    assert len(delivered) == 2


def test_runner_requires_one_of_the_two_probes():
    with pytest.raises(ValueError, match="ровно один"):
        LatencyRunner()


def test_make_batch_probe_measures_known_profiles_with_the_app_settings(monkeypatch):
    seen: dict = {}

    def fake_probe_profiles(profiles, *, settings, binary_path, on_result):
        seen["ids"] = [profile.id for profile in profiles]
        seen["settings"] = settings
        seen["binary"] = binary_path
        for profile in profiles:
            on_result(profile.id, 42)

    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)
    known = {1: SimpleNamespace(id=1), 3: SimpleNamespace(id=3)}
    context = SimpleNamespace(
        profiles=SimpleNamespace(get_profile=known.get),
        config="настройки",
        xray_manager=SimpleNamespace(binary_path="/opt/xray"),
    )
    results: dict = {}

    make_batch_probe(context)([1, 2, 3], results.__setitem__)

    # Профиля 2 уже нет: в замер он не идёт, а -1 ему допишет сам runner.
    assert seen == {"ids": [1, 3], "settings": "настройки", "binary": "/opt/xray"}
    assert results == {1: 42, 3: 42}
