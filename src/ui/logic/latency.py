"""Bounded background runner for profile latency probes.

GTK-free: результаты доставляются через `dispatch` (по умолчанию GLib.idle_add),
чтобы модуль можно было тестировать без дисплея.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger("tenga.ui.latency")

ProbeFn = Callable[[int], int]
ResultFn = Callable[[int, int], None]
BatchProbeFn = Callable[[list[int], ResultFn], None]
DispatchFn = Callable[..., object]


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


def make_batch_probe(context: Any) -> BatchProbeFn:
    """Batch probe bound to the application context.

    Контекст читается в момент замера, а не при создании: список профилей и
    настройки транспорта к этому времени могли измениться.
    """

    def batch_probe(profile_ids: list[int], emit: ResultFn) -> None:
        from src.core.batch_probe import probe_profiles

        found = (context.profiles.get_profile(profile_id) for profile_id in profile_ids)
        probe_profiles(
            [profile for profile in found if profile is not None],
            settings=context.config,
            binary_path=context.xray_manager.binary_path,
            on_result=emit,
        )

    return batch_probe


class PingProgress:
    """Per-group progress of one latency run.

    Замер приходит по профилям, а показывается по группам: здесь хранится,
    какой профиль к какой группе относится и сколько результатов уже пришло.
    """

    def __init__(self, groups: Mapping[int, Iterable[int]]) -> None:
        self._group_of: dict[int, int] = {}
        self._total: dict[int, int] = {}
        self._done: dict[int, int] = {}
        for group_id, profile_ids in groups.items():
            ids = list(profile_ids)
            if not ids:
                continue
            self._total[group_id] = len(ids)
            self._done[group_id] = 0
            for profile_id in ids:
                self._group_of[profile_id] = group_id

    @property
    def group_ids(self) -> set[int]:
        return set(self._total)

    def record(self, profile_id: int) -> int | None:
        """Count one result; return its group, or None if it is not expected."""
        # pop: повторный результат того же профиля не должен двигать счётчик.
        group_id = self._group_of.pop(profile_id, None)
        if group_id is not None:
            self._done[group_id] += 1
        return group_id

    def state(self, group_id: int) -> tuple[int, int] | None:
        """Return (done, total) for a group of this run."""
        if group_id not in self._total:
            return None
        return self._done[group_id], self._total[group_id]

    def fraction(self, group_id: int) -> float | None:
        state = self.state(group_id)
        if state is None:
            return None
        done, total = state
        return done / total


class LatencyRunner:
    """Run latency probes for many profiles in the background.

    Два режима. `batch_probe` получает весь набор сразу и сам отдаёт результаты
    по мере готовности — так работает замер одним процессом ядра. `probe`
    меряет по одному профилю в пуле потоков; он остался для подмены в тестах.
    """

    def __init__(
        self,
        probe: ProbeFn | None = None,
        *,
        batch_probe: BatchProbeFn | None = None,
        max_workers: int = 4,
        dispatch: DispatchFn = _default_dispatch,
    ) -> None:
        if (probe is None) == (batch_probe is None):
            raise ValueError("нужен ровно один из probe и batch_probe")

        self._probe = probe
        self._batch_probe = batch_probe
        self._max_workers = max_workers
        self._dispatch = dispatch
        self._lock = threading.Lock()
        self._busy = False
        self._thread: threading.Thread | None = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def run(
        self,
        profile_ids: Iterable[int],
        *,
        on_result: ResultFn,
        on_done: Callable[[], None],
    ) -> bool:
        """Start probing. Returns False if a run is already in progress."""
        ids = list(profile_ids)
        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def _safe_probe(profile_id: int) -> int:
            # BaseException too: anything escaping here would propagate out of
            # pool.map and abort the delivery of every remaining result, leaving
            # those profiles stuck on the "testing" placeholder forever.
            try:
                return int(self._probe(profile_id))
            except BaseException as e:
                logger.exception("Latency probe failed for profile %s: %s", profile_id, e)
                return -1

        def _finished() -> None:
            # Released here rather than in the worker: until this runs, on_done
            # of this run is still queued, and accepting another run would let
            # the two interleave on the shared UI state.
            with self._lock:
                self._busy = False
            on_done()

        def _run_batch() -> None:
            reported: set[int] = set()

            def emit(profile_id: int, latency_ms: int) -> None:
                if profile_id in reported:
                    return
                reported.add(profile_id)
                self._dispatch(on_result, profile_id, int(latency_ms))

            try:
                self._batch_probe(ids, emit)
            except BaseException as e:
                logger.exception("Batch latency probe failed: %s", e)
            finally:
                # Что бы ни случилось с замером, ни один профиль не должен
                # остаться с заглушкой «проверяется».
                for profile_id in ids:
                    if profile_id not in reported:
                        self._dispatch(on_result, profile_id, -1)

        def _run_pool() -> None:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                probes = pool.map(_safe_probe, ids)
                for profile_id, latency in zip(ids, probes, strict=True):
                    self._dispatch(on_result, profile_id, latency)

        def _worker() -> None:
            try:
                if self._batch_probe is not None:
                    _run_batch()
                else:
                    _run_pool()
            finally:
                self._dispatch(_finished)

        self._thread = threading.Thread(target=_worker, name="latency-runner", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current run finishes (tests only)."""
        if self._thread is not None:
            self._thread.join(timeout)
