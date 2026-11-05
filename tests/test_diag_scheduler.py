import threading
import time

import pytest

from src.diag.budget import ScheduleSession
from src.diag.models import (
    DiagnosticFailure,
    DiagnosticRequest,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.scheduler import DiagnosticScheduler, DiagnosticTask, SocketRegistry


def task(task_id, origin="o", max_bytes=0, execute=None):
    def default():
        return observation(task_id)

    return DiagnosticTask(
        task_id, "target", origin, ProbeRoute.DIRECT, ProbeStage.HTTP, max_bytes, execute or default
    )


def observation(task_id, status=ProbeStatus.SUCCESS):
    return ProbeObservation(task_id, "target", ProbeRoute.DIRECT, ProbeStage.HTTP, status)


def run(tasks, *, scheduler=None, **request):
    collected = []
    (scheduler or DiagnosticScheduler()).run(
        tasks, ScheduleSession(DiagnosticRequest(**request)), collected.append
    )
    return {item.id: item for item in collected}


class Gauge:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = {}
        self.peak = {}

    def probe(self, key, task_id):
        with self.lock:
            for name in (key, "*"):
                self.current[name] = self.current.get(name, 0) + 1
                self.peak[name] = max(self.peak.get(name, 0), self.current[name])
        time.sleep(0.02)
        with self.lock:
            for name in (key, "*"):
                self.current[name] -= 1
        return observation(task_id)


def test_concurrency_is_four_and_two_per_origin():
    gauge = Gauge()
    tasks = []
    for index in range(20):
        origin = f"origin-{index % 3}"
        name = f"t{index}"
        tasks.append(task(name, origin, execute=lambda o=origin, n=name: gauge.probe(o, n)))
    assert len(run(tasks)) == 20
    assert gauge.peak["*"] == 4
    assert all(gauge.peak[f"origin-{i}"] <= 2 for i in range(3))


def test_budget_exhaustion_skips_with_budget_code():
    result = run([task("a", max_bytes=8), task("b", max_bytes=8)], max_payload_bytes=10)
    statuses = sorted(item.status.name for item in result.values())
    assert statuses == ["SKIPPED", "SUCCESS"]
    skipped = next(i for i in result.values() if i.status is ProbeStatus.SKIPPED)
    assert skipped.failure_code is DiagnosticFailure.BUDGET


def test_attempt_limit_applies_too():
    result = run([task(f"t{i}", f"o{i}") for i in range(3)], max_attempts=2)
    assert sum(i.failure_code is DiagnosticFailure.BUDGET for i in result.values()) == 1


def test_deadline_cancels_running_and_skips_rest():
    release = threading.Event()
    registry = SocketRegistry()

    def stuck(name):
        release.wait(5)
        return observation(name)

    tasks = [task(f"r{i}", f"o{i}", execute=lambda n=f"r{i}": stuck(n)) for i in range(4)]
    tasks.append(task("waiting", "x"))
    result = run(tasks, scheduler=DiagnosticScheduler([registry]), deadline_ms=50)
    release.set()
    assert result["r0"].status is ProbeStatus.CANCELLED
    assert result["r0"].failure_code is DiagnosticFailure.DEADLINE
    assert result["waiting"].status is ProbeStatus.SKIPPED
    assert result["waiting"].failure_code is DiagnosticFailure.DEADLINE


def test_zero_remaining_skips_everything():
    now = [0]
    session = ScheduleSession(DiagnosticRequest(deadline_ms=1), clock=lambda: now[0])
    now[0] = 10
    collected = []
    DiagnosticScheduler().run([task("a")], session, collected.append)
    assert collected[0].failure_code is DiagnosticFailure.DEADLINE
    assert collected[0].status is ProbeStatus.SKIPPED


def test_interrupt_closes_sockets_and_stops_publishing():
    import socket

    registry = SocketRegistry()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    sock = socket.create_connection(server.getsockname())
    registry.add(sock)
    started = threading.Event()
    scheduler = DiagnosticScheduler([registry])

    def blocked():
        started.set()
        try:
            sock.recv(1)
        except OSError:
            pass
        return observation("blocked")

    collected = []
    worker = threading.Thread(
        target=scheduler.run,
        args=(
            [task("blocked", execute=blocked)],
            ScheduleSession(DiagnosticRequest()),
            collected.append,
        ),
    )
    worker.start()
    assert started.wait(2)
    scheduler.interrupt(DiagnosticFailure.USER_CANCELLED)
    worker.join(2)
    assert not worker.is_alive()
    assert collected == []
    assert scheduler.interrupted is DiagnosticFailure.USER_CANCELLED
    server.close()


def test_registry_refuses_after_close():
    import socket

    registry = SocketRegistry()
    registry.close_all()
    with pytest.raises(OSError, match="stopped"):
        registry.add(socket.socket())


def test_probe_exception_becomes_inconclusive_io():
    def boom():
        raise RuntimeError("1.2.3.4 failed")

    result = run([task("a", execute=boom)])
    assert result["a"].status is ProbeStatus.INCONCLUSIVE
    assert result["a"].failure_code is DiagnosticFailure.IO


def test_foreign_observation_is_rejected():
    result = run([task("a", execute=lambda: observation("b"))])
    assert result["a"].failure_code is DiagnosticFailure.IO


def test_batches_are_capped_and_ids_unique():
    with pytest.raises(ValueError, match="batch"):
        run([task(f"t{i}", f"o{i}") for i in range(161)])
    with pytest.raises(ValueError, match="batch"):
        run([task("a"), task("a")])
