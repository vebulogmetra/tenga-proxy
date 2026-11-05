"""Планировщик проб: порт DiagnosticScheduler.kt на потоках.

Поток нельзя отменить, как корутину, поэтому пробы регистрируют свои сокеты: отмена и срок
закрывают их, а поздний результат отброшенной задачи просто не публикуется.
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.diag.budget import ScheduleSession
from src.diag.models import (
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)

logger = logging.getLogger("tenga.diag")

MAX_CONCURRENCY = 4
MAX_PER_ORIGIN = 2
MAX_BATCH = 160


@dataclass(frozen=True)
class DiagnosticTask:
    id: str
    target_id: str
    origin: str
    route: ProbeRoute
    stage: ProbeStage
    max_bytes: int
    execute: Callable[[], ProbeObservation]


class SocketRegistry:
    """Открытые сокеты проб: закрытие прерывает поток, застрявший в connect или recv."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: set[socket.socket] = set()
        self._closed = False

    def add(self, sock: socket.socket) -> None:
        with self._lock:
            if not self._closed:
                self._sockets.add(sock)
                return
        sock.close()
        raise OSError("diagnostic run is stopped")

    def discard(self, sock: socket.socket) -> None:
        with self._lock:
            self._sockets.discard(sock)

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            sockets, self._sockets = self._sockets, set()
        for sock in sockets:
            _force_close(sock)


def _force_close(sock: socket.socket) -> None:
    # shutdown будит поток, ждущий в recv: один close на Linux его не разбудит.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def task_observation(
    task: DiagnosticTask, status: ProbeStatus, failure: DiagnosticFailure
) -> ProbeObservation:
    return ProbeObservation(
        task.id, task.target_id, task.route, task.stage, status, failure_code=failure
    )


class DiagnosticScheduler:
    """Выполняет пакет: не больше 4 проб сразу и 2 на один origin, в пределах бюджета и срока."""

    def __init__(self, sockets: Iterable[SocketRegistry] = ()) -> None:
        self._sockets = tuple(sockets)
        self._lock = threading.Lock()
        self._interrupt: DiagnosticFailure | None = None
        self._wake: queue.SimpleQueue = queue.SimpleQueue()

    def interrupt(self, reason: DiagnosticFailure) -> None:
        """Остановить текущий и последующие пакеты; вызывается из любого потока."""
        with self._lock:
            if self._interrupt is not None:
                return
            self._interrupt = reason
        for registry in self._sockets:
            registry.close_all()
        self._wake.put(None)

    @property
    def interrupted(self) -> DiagnosticFailure | None:
        with self._lock:
            return self._interrupt

    def run(
        self,
        tasks: list[DiagnosticTask],
        session: ScheduleSession,
        publish: Callable[[ProbeObservation], None],
    ) -> None:
        if len(tasks) > MAX_BATCH or len({t.id for t in tasks}) != len(tasks):
            raise ValueError("bad diagnostic batch")
        if any(t.max_bytes < 0 or not t.id.strip() or not t.origin.strip() for t in tasks):
            raise ValueError("bad diagnostic task")

        pending = list(tasks)
        running: dict[str, DiagnosticTask] = {}
        origins: dict[str, int] = {}

        def launch() -> None:
            for task in list(pending):
                if len(running) >= MAX_CONCURRENCY:
                    return
                if origins.get(task.origin, 0) >= MAX_PER_ORIGIN:
                    continue
                pending.remove(task)
                if session.remaining_ms() == 0:
                    publish(task_observation(task, ProbeStatus.SKIPPED, DiagnosticFailure.DEADLINE))
                    continue
                if not session.budget.reserve(task.max_bytes):
                    publish(task_observation(task, ProbeStatus.SKIPPED, DiagnosticFailure.BUDGET))
                    continue
                running[task.id] = task
                origins[task.origin] = origins.get(task.origin, 0) + 1
                threading.Thread(
                    target=self._execute, args=(task, results), daemon=True, name="diag-probe"
                ).start()

        results = self._wake
        while pending or running:
            reason = self.interrupted
            if reason is not None:
                # Прерванные задачи достаются вызывающему: он помечает их причиной прерывания.
                return
            launch()
            if not running:
                if pending:
                    continue
                return
            remaining = session.remaining_ms()
            if remaining == 0:
                self._expire(running, pending, publish)
                return
            try:
                item = results.get(timeout=remaining / 1000)
            except queue.Empty:
                self._expire(running, pending, publish)
                return
            # Флаг ставится раньше закрытия сокетов: результат, разбуженный закрытием, не публикуем.
            if item is None or self.interrupted is not None:
                continue
            task, observation = item
            if running.pop(task.id, None) is None:
                continue  # результат задачи прошлого пакета, уже помеченной сроком
            origins[task.origin] -= 1
            publish(observation)

    def _expire(self, running, pending, publish) -> None:
        for task in running.values():
            publish(task_observation(task, ProbeStatus.CANCELLED, DiagnosticFailure.DEADLINE))
        for task in pending:
            publish(task_observation(task, ProbeStatus.SKIPPED, DiagnosticFailure.DEADLINE))
        for registry in self._sockets:
            registry.close_all()

    @staticmethod
    def _execute(task: DiagnosticTask, results: queue.SimpleQueue) -> None:
        try:
            observation = task.execute()
            if (observation.id, observation.target_id, observation.route, observation.stage) != (
                task.id,
                task.target_id,
                task.route,
                task.stage,
            ):
                raise ValueError(f"probe returned a foreign observation for {task.id}")
        except Exception:
            # Текст исключения может содержать адрес: в отчёт идёт только код, детали — в журнал.
            logger.debug("Проба %s завершилась исключением", task.id, exc_info=True)
            observation = task_observation(task, ProbeStatus.INCONCLUSIVE, DiagnosticFailure.IO)
        results.put((task, observation))
