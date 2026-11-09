"""Bounded background runner for profile latency probes.

GTK-free: результаты доставляются через `dispatch` (по умолчанию GLib.idle_add),
чтобы модуль можно было тестировать без дисплея. Из системы модуль берёт только фасады
`src.sys` без тулкита: путь замера мимо туннеля.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.core.batch_probe import ProbeRoute
from src.core.probe_result import ProbeFailure, ProbeResult
from src.sys import netbind
from src.sys.resolver import system_dns_servers

logger = logging.getLogger("tenga.ui.latency")

# Проба одного профиля — подмена в тестах; может вернуть и число, как раньше.
ProbeFn = Callable[[int], "ProbeResult | int"]
# None — замер прервался ошибкой нашего кода: о сервере он ничего не узнал.
ResultFn = Callable[[int, "ProbeResult | None"], None]
BatchProbeFn = Callable[[list[int], Callable[[int, "ProbeResult | int"], None]], None]
DispatchFn = Callable[..., object]


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


PROBE_UNAVAILABLE = "Замер при активном TUN недоступен: нет маршрута мимо туннеля"


def as_probe_result(value: ProbeResult | int) -> ProbeResult:
    """Результат пробы; число от подставной пробы: < 0 — отказ, иначе задержка."""
    if isinstance(value, ProbeResult):
        return value
    if int(value) < 0:
        return ProbeResult.failed(ProbeFailure.UNREACHABLE)
    return ProbeResult.ok(int(value))


class ProbeUnavailable(RuntimeError):
    """Замер сейчас невозможен; текст показывается пользователю."""


def probe_route(context: Any) -> ProbeRoute | None:
    """Путь проб мимо туннеля: при TUN и при заблокированном трафике, иначе None.

    Зовётся из потока замера, а не из контроллера: на Windows поиск интерфейса — снимок сети
    через PowerShell, в главном потоке он подвесил бы окно.
    """
    state = getattr(context, "proxy_state", None)
    if state is None:
        return None
    in_tun = state.is_running and state.started_mode == "tun"
    if not in_tun and not getattr(state, "traffic_blocked", False):
        return None

    tun_name = (getattr(context.config, "tun_name", "") or "xray0").strip()
    interface = netbind.physical_interface(exclude=(tun_name,))
    if interface is None or not netbind.binding_confirmed(interface):
        raise ProbeUnavailable(PROBE_UNAVAILABLE)
    return ProbeRoute(
        interface=interface,
        mark=netbind.socket_mark(),
        dns_servers=tuple(system_dns_servers(interface)),
    )


def make_batch_probe(
    context: Any, on_unavailable: Callable[[str], None] | None = None
) -> BatchProbeFn:
    """Batch probe bound to the application context.

    Контекст читается в момент замера, а не при создании: список профилей, настройки и
    режим сеанса к этому времени могли измениться. `on_unavailable` получает текст отказа,
    когда пути мимо туннеля нет; результата профили при этом не получают, прежний остаётся.
    """

    def batch_probe(profile_ids: list[int], emit: Callable[[int, ProbeResult], None]) -> None:
        from src.core.batch_probe import probe_profiles

        try:
            route = probe_route(context)
        except ProbeUnavailable as e:
            if on_unavailable is not None:
                on_unavailable(str(e))
            raise

        found = (context.profiles.get_profile(profile_id) for profile_id in profile_ids)
        probe_profiles(
            [profile for profile in found if profile is not None],
            settings=context.config,
            binary_path=context.xray_manager.binary_path,
            on_result=emit,
            route=route,
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
        self.last_run_complete = False
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
            self.last_run_complete = True

        def _safe_probe(profile_id: int) -> ProbeResult | None:
            # BaseException too: anything escaping here would propagate out of
            # pool.map and abort the delivery of every remaining result, leaving
            # those profiles stuck on the "testing" placeholder forever.
            try:
                return as_probe_result(self._probe(profile_id))
            except BaseException as e:
                self.last_run_complete = False
                logger.exception("Latency probe failed for profile %s: %s", profile_id, e)
                return None

        def _finished() -> None:
            # Released here rather than in the worker: until this runs, on_done
            # of this run is still queued, and accepting another run would let
            # the two interleave on the shared UI state.
            with self._lock:
                self._busy = False
            on_done()

        def _run_batch() -> None:
            reported: set[int] = set()

            def emit(profile_id: int, result: ProbeResult | int) -> None:
                if profile_id in reported:
                    return
                reported.add(profile_id)
                self._dispatch(on_result, profile_id, as_probe_result(result))

            try:
                self._batch_probe(ids, emit)
            except BaseException as e:
                self.last_run_complete = False
                logger.exception("Batch latency probe failed: %s", e)
            finally:
                # Что бы ни случилось с замером, ни один профиль не должен
                # остаться с заглушкой «проверяется». None, а не отказ: сбой
                # замера не говорит, что сервер не работает.
                for profile_id in ids:
                    if profile_id not in reported:
                        self._dispatch(on_result, profile_id, None)

        def _run_pool() -> None:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                probes = pool.map(_safe_probe, ids)
                for profile_id, result in zip(ids, probes, strict=True):
                    self._dispatch(on_result, profile_id, result)

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


def failed_profile_ids(
    profile_ids: Iterable[int],
    results: Mapping[int, ProbeResult | None],
    *,
    complete: bool,
    active_id: int | None = None,
) -> list[int]:
    """Серверы, отказавшие при полном замере, в котором хоть один ответил.

    Пропуск или None у любого профиля — замер неполный, и удалять нечего.
    """
    ids = list(profile_ids)
    if (
        not complete
        or set(ids) != set(results)
        or any(result is None for result in results.values())
        or not any(result.succeeded for result in results.values())
    ):
        return []
    return [
        profile_id
        for profile_id in ids
        if results[profile_id].failure is not None and profile_id != active_id
    ]
