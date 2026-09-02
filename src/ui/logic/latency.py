"""Bounded background runner for profile latency probes.

GTK-free: результаты доставляются через `dispatch` (по умолчанию GLib.idle_add),
чтобы модуль можно было тестировать без дисплея.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("tenga.ui.latency")

ProbeFn = Callable[[int], int]
ResultFn = Callable[[int, int], None]
DispatchFn = Callable[..., object]


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


class LatencyRunner:
    """Run latency probes for many profiles with bounded parallelism."""

    def __init__(
        self,
        probe: ProbeFn,
        *,
        max_workers: int = 4,
        dispatch: DispatchFn = _default_dispatch,
    ) -> None:
        self._probe = probe
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
            try:
                return int(self._probe(profile_id))
            except Exception as e:
                logger.exception("Latency probe failed for profile %s: %s", profile_id, e)
                return -1

        def _worker() -> None:
            try:
                with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                    probes = pool.map(_safe_probe, ids)
                    for profile_id, latency in zip(ids, probes, strict=True):
                        self._dispatch(on_result, profile_id, latency)
            finally:
                with self._lock:
                    self._busy = False
                self._dispatch(on_done)

        self._thread = threading.Thread(target=_worker, name="latency-runner", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current run finishes (tests only)."""
        if self._thread is not None:
            self._thread.join(timeout)
