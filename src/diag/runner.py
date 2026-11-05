"""Запуск проверки: порт RunNetworkDiagnostics.kt и фабрики окружения.

`run` блокирует вызывающий поток и шлёт события в `on_event` из него же: порядок наблюдений
один, а переход в главный цикл — забота интерфейса.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from src.core.http_probe import ProbeEndpoint
from src.diag.assess.allowlist import ClassificationContext, assess_allowlist
from src.diag.assess.causes import assess_causes
from src.diag.assess.classifier import classify
from src.diag.assess.dns import assess_dns
from src.diag.assess.services import PURPOSES as SERVICE_PURPOSES
from src.diag.assess.services import assess_services
from src.diag.backend import DesktopProbeBackend
from src.diag.budget import ScheduleSession
from src.diag.catalog import (
    DiagnosticCatalog,
    DiagnosticPurpose,
    DiagnosticTarget,
    PlacementRegistry,
    load_catalog,
)
from src.diag.models import (
    CAUSES_DEADLINE_MS,
    MAX_DETAIL_TARGETS,
    AddressFamily,
    AllowlistAssessment,
    DiagnosticFailure,
    DiagnosticReport,
    DiagnosticRequest,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.network import DirectPolicy, NetworkState, NetworkWatcher, read_network_state
from src.diag.plan import DiagnosticProbePlan
from src.diag.probes.support import ProbeContext
from src.diag.scheduler import DiagnosticScheduler, DiagnosticTask, SocketRegistry
from src.diag.session import TunnelSessionSource
from src.sys import netbind
from src.sys.resolver import system_dns_servers

logger = logging.getLogger("tenga.diag")

MAX_PLANNED = 1024
_MONITOR_PERIOD_S = 0.25
_NETWORK_PERIOD_S = 1.0
_BATCH = 160


class DiagnosticRunChange(Enum):
    NETWORK_CHANGED = "NETWORK_CHANGED"
    VPN_SESSION_CHANGED = "VPN_SESSION_CHANGED"


@dataclass(frozen=True)
class Started:
    context: DiagnosticRunContext
    targets: tuple[DiagnosticTarget, ...] = ()


@dataclass(frozen=True)
class ObservationEvent:
    observation: ProbeObservation


@dataclass(frozen=True)
class Updated:
    report: DiagnosticReport


@dataclass(frozen=True)
class Finished:
    report: DiagnosticReport


DiagnosticEvent = Started | ObservationEvent | Updated | Finished


class RunEnvironment(Protocol):
    catalog: DiagnosticCatalog
    sockets: tuple[SocketRegistry, ...]
    verified_placement_groups: frozenset[str]
    allowlist_complete: bool
    services_started: bool
    services_complete: bool
    dns_started: bool
    dns_complete: bool
    compare_services_through_tunnel: bool

    def tasks(self, phase: int, observations: list) -> list[DiagnosticTask] | None: ...

    def follow_up_tasks(self, phase: int, observations: list) -> list[DiagnosticTask]: ...

    def phase_completed(self, phase: int) -> None: ...

    def poll_change(self) -> DiagnosticRunChange | None: ...

    def tunnel_lost(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DiagnosticSources:
    """Что проверке нужно от приложения: читается заново при каждом опросе."""

    policy: Callable[[], DirectPolicy]
    endpoint: Callable[[], ProbeEndpoint | None]


class DesktopEnvironment:
    def __init__(self, request: DiagnosticRequest, sources: DiagnosticSources):
        self.catalog = load_catalog()
        placements = PlacementRegistry.load()
        policy = sources.policy()
        self.network: NetworkState = read_network_state(policy)
        self._watcher = NetworkWatcher(self.network, sources.policy, read_network_state)
        self._direct_sockets = SocketRegistry()
        self._tunnel_sockets = SocketRegistry()
        self.sockets = (self._direct_sockets, self._tunnel_sockets)
        self._sessions = TunnelSessionSource(sources.endpoint)
        self._session = self._sessions.current() if request.compare_active_tunnel else None
        self._next_network_check = time.monotonic() + _NETWORK_PERIOD_S
        interface = self.network.interface
        direct = ProbeContext(
            bind=(lambda sock: netbind.bind_socket(sock, interface)) if interface else None,
            under_tun=self.network.under_tun,
            sockets=self._direct_sockets,
        )
        tunnel = ProbeContext(sockets=self._tunnel_sockets)
        self._servers_lock = threading.Lock()
        self._servers: list[str] | None = None
        backend = DesktopProbeBackend(
            self.network,
            direct,
            tunnel,
            self._sessions,
            self._session,
            compare_tunnel=request.compare_active_tunnel,
            dns_servers=self._dns_servers,
        )
        self._backend = backend
        self._plan = DiagnosticProbePlan(self.catalog, request, backend, placements)

    def _dns_servers(self) -> list[str]:
        with self._servers_lock:
            if self._servers is None:
                interface = self.network.interface
                self._servers = list(system_dns_servers(interface)) if interface else []
            return self._servers

    def __getattr__(self, name: str):
        return getattr(self._plan, name)

    def tasks(self, phase: int, observations: list) -> list[DiagnosticTask] | None:
        if not self.network.available:
            if phase != 0:
                return None
            return [
                DiagnosticTask(
                    "network", "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, 0,
                    self._backend.baseline,
                )
            ]  # fmt: skip
        return self._plan.tasks(phase, observations)

    def poll_change(self) -> DiagnosticRunChange | None:
        now = time.monotonic()
        if now >= self._next_network_check:
            self._next_network_check = now + _NETWORK_PERIOD_S
            if self._watcher.changed():
                return DiagnosticRunChange.NETWORK_CHANGED
        if self._session is not None and not self._sessions.is_current(self._session):
            return DiagnosticRunChange.VPN_SESSION_CHANGED
        return None

    def tunnel_lost(self) -> None:
        self._tunnel_sockets.close_all()

    def close(self) -> None:
        for registry in self.sockets:
            registry.close_all()


def _cancelled(task: DiagnosticTask, reason: DiagnosticFailure) -> ProbeObservation:
    return ProbeObservation(
        task.id, task.target_id, task.route, task.stage, ProbeStatus.CANCELLED, failure_code=reason
    )


_STOP_REASONS = {
    DiagnosticTermination.USER_CANCELLED: DiagnosticFailure.USER_CANCELLED,
    DiagnosticTermination.BACKGROUND: DiagnosticFailure.USER_CANCELLED,
    DiagnosticTermination.NETWORK_CHANGED: DiagnosticFailure.NETWORK_CHANGED,
}


class DiagnosticRunner:
    def __init__(
        self,
        open_environment: Callable[[DiagnosticRequest], RunEnvironment],
        app_version: str,
        epoch_seconds: Callable[[], float] = time.time,
    ):
        self._open = open_environment
        self._app_version = app_version
        self._epoch_seconds = epoch_seconds
        self._lock = threading.Lock()
        self._running = False
        self._stop_requested: DiagnosticTermination | None = None
        self._scheduler: DiagnosticScheduler | None = None

    def cancel(self, reason: DiagnosticTermination = DiagnosticTermination.USER_CANCELLED) -> None:
        """Можно звать из любого потока; задачи закрываются, отчёт придёт в Finished."""
        with self._lock:
            if not self._running:
                return
            self._stop_requested = self._stop_requested or reason
            scheduler = self._scheduler
        if scheduler is not None:
            scheduler.interrupt(_STOP_REASONS[reason])

    def run(self, request: DiagnosticRequest, on_event: Callable[[DiagnosticEvent], None]) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("diagnostic run is already active")
            self._running = True
            self._stop_requested = None
            self._scheduler = None
        try:
            _Run(self, request, on_event).execute()
        finally:
            with self._lock:
                self._running = False
                self._scheduler = None

    # Внутренний протокол с _Run.
    def _attach(self, scheduler: DiagnosticScheduler) -> DiagnosticTermination | None:
        with self._lock:
            self._scheduler = scheduler
            return self._stop_requested

    def _stop_reason(self) -> DiagnosticTermination | None:
        with self._lock:
            return self._stop_requested


class _Run:
    def __init__(self, runner: DiagnosticRunner, request, on_event):
        self.runner = runner
        self.request = request
        self.on_event = on_event
        self.context = DiagnosticRunContext(
            DiagnosticRunContext.new_run_id(),
            "bundled",
            runner._app_version,
            section=request.section,
        )
        self.observations: dict[str, ProbeObservation] = {}
        self.planned: dict[str, DiagnosticTask] = {}
        self.session = ScheduleSession(request)
        self.tunnel_lost = threading.Event()
        self.environment: RunEnvironment | None = None
        self.termination = DiagnosticTermination.COMPLETED
        self.network_changed = False
        self.finished = False
        self.started = False
        self.scheduler: DiagnosticScheduler | None = None
        self.completed_allowlist: AllowlistAssessment | None = None
        self.monitor_stop = threading.Event()

    def snapshot(self) -> DiagnosticReport:
        report = DiagnosticReport(
            self.context, tuple(self.observations.values()), termination=self.termination
        )
        environment = self.environment
        if environment is None:
            return report
        catalog = environment.catalog
        section = self.request.section
        now = self.runner._epoch_seconds()
        stable = not self.network_changed and self.termination is DiagnosticTermination.COMPLETED
        context = ClassificationContext(
            now,
            direct_context_stable=self.finished and stable,
            tunnel_comparison_valid=not self.network_changed and not self.tunnel_lost.is_set(),
            verified_placement_groups=environment.verified_placement_groups,
        )
        allowlist = None
        if section in (None, DiagnosticSection.ALLOWLIST):
            if not self.network_changed and self.completed_allowlist is not None:
                allowlist = self.completed_allowlist
            else:
                done = self.finished or environment.allowlist_complete
                allowlist = assess_allowlist(
                    report,
                    catalog,
                    replace(context, direct_context_stable=done and stable),
                )
                allowlist = replace(allowlist, completed=done)
                if environment.allowlist_complete and not self.network_changed:
                    self.completed_allowlist = allowlist
        services = None
        if section in (None, DiagnosticSection.SERVICES):
            services = assess_services(
                catalog,
                report.observations,
                started=environment.services_started,
                completed=self.finished or environment.services_complete,
                compare_tunnel=environment.compare_services_through_tunnel,
                network_changed=self.network_changed,
                tunnel_changed=self.tunnel_lost.is_set(),
            )
        dns = None
        if section in (None, DiagnosticSection.DNS):
            dns = assess_dns(
                catalog,
                report.observations,
                started=environment.dns_started,
                completed=self.finished or environment.dns_complete,
                network_changed=self.network_changed,
            )
        causes = None
        if section is DiagnosticSection.DETAILS:
            causes = assess_causes(report.observations, self.request.detail_target_ids)
        return dataclasses.replace(
            report,
            findings=classify(report, catalog, context),
            allowlist_assessment=allowlist,
            service_assessment=services,
            dns_assessment=dns,
            cause_assessment=causes,
        )

    def publish(self, observation: ProbeObservation) -> None:
        self.observations[observation.id] = observation
        self.on_event(ObservationEvent(observation))
        self.on_event(Updated(self.snapshot()))

    def _guard(self, task: DiagnosticTask) -> DiagnosticTask:
        """Потеря туннеля отменяет только пробы туннеля: прямые идут дальше."""
        if task.route is ProbeRoute.DIRECT:
            return task

        def execute() -> ProbeObservation:
            if self.tunnel_lost.is_set():
                return _cancelled(task, DiagnosticFailure.VPN_SESSION_CHANGED)
            box: list = []
            done = threading.Event()

            def work() -> None:
                try:
                    box.append(task.execute())
                except Exception as error:
                    box.append(error)
                done.set()

            threading.Thread(target=work, daemon=True, name="diag-tunnel-probe").start()
            while not done.wait(0.05):
                if self.tunnel_lost.is_set():
                    return _cancelled(task, DiagnosticFailure.VPN_SESSION_CHANGED)
            if self.tunnel_lost.is_set():
                return _cancelled(task, DiagnosticFailure.VPN_SESSION_CHANGED)
            if isinstance(box[0], Exception):
                raise box[0]
            return box[0]

        return dataclasses.replace(task, execute=execute)

    def run_tasks(self, tasks: list[DiagnosticTask]) -> bool:
        if len(self.planned) + len(tasks) > MAX_PLANNED:
            raise ValueError("diagnostic plan is too large")
        for task in tasks:
            if task.id in self.planned:
                raise ValueError("duplicate diagnostic task")
            self.planned[task.id] = task
        guarded = [self._guard(task) for task in tasks]
        for start in range(0, len(guarded), _BATCH):
            self.scheduler.run(guarded[start : start + _BATCH], self.session, self.publish)
            if self.scheduler.interrupted is not None:
                return False
        return True

    def _monitor(self) -> None:
        while not self.monitor_stop.wait(_MONITOR_PERIOD_S):
            try:
                change = self.environment.poll_change()
            except Exception:
                logger.debug("Опрос сети не удался", exc_info=True)
                continue
            if change is DiagnosticRunChange.NETWORK_CHANGED:
                self.network_changed = True
                self.termination = DiagnosticTermination.NETWORK_CHANGED
                self.scheduler.interrupt(DiagnosticFailure.NETWORK_CHANGED)
                return
            if change is DiagnosticRunChange.VPN_SESSION_CHANGED and not self.tunnel_lost.is_set():
                self.tunnel_lost.set()
                self.environment.tunnel_lost()

    def _phases(self) -> None:
        environment = self.environment
        for phase in range(9):
            tasks = environment.tasks(phase, list(self.observations.values()))
            if tasks is None:
                return
            if not self.run_tasks(tasks):
                return
            follow_up = environment.follow_up_tasks(phase, list(self.observations.values()))
            if not self.run_tasks(follow_up):
                return
            environment.phase_completed(phase)
            self.on_event(Updated(self.snapshot()))

    def execute(self) -> None:
        monitor = None
        try:
            self.environment = self.runner._open(self.request)
            self.context = replace(
                self.context, catalog_version=str(self.environment.catalog.catalog_version)
            )
            self.on_event(Started(self.context, tuple(self.environment.catalog.targets)))
            self.started = True
            self.scheduler = DiagnosticScheduler(self.environment.sockets)
            stopped = self.runner._attach(self.scheduler)
            if stopped is not None:
                self.scheduler.interrupt(_STOP_REASONS[stopped])
            monitor = threading.Thread(target=self._monitor, daemon=True, name="diag-monitor")
            monitor.start()
            self._phases()
            self._finish_termination()
        except Exception as error:
            # Текст исключения в отчёт не идёт: там могут быть адреса.
            logger.warning("Проверка сети прервалась: %s", type(error).__name__, exc_info=True)
            self.termination = DiagnosticTermination.INTERNAL_ERROR
            if not self.started:
                self.on_event(Started(self.context))
                self.started = True
            failure = (
                DiagnosticFailure.SYSTEM_RESTRICTED
                if isinstance(error, PermissionError)
                else DiagnosticFailure.IO
            )
            self.publish(
                ProbeObservation(
                    "run-error", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK,
                    ProbeStatus.INCONCLUSIVE, failure_code=failure,
                )
            )  # fmt: skip
        finally:
            self.monitor_stop.set()
            if self.environment is not None:
                try:
                    self.environment.close()
                except Exception:
                    logger.debug("Закрытие окружения проверки не удалось", exc_info=True)
        self.finished = True
        self.on_event(Finished(self.snapshot()))

    def _finish_termination(self) -> None:
        stopped = self.runner._stop_reason()
        if stopped is not None and self.termination is DiagnosticTermination.COMPLETED:
            self.termination = stopped
        if self.termination is not DiagnosticTermination.COMPLETED:
            reason = (
                DiagnosticFailure.NETWORK_CHANGED
                if self.network_changed
                else _STOP_REASONS.get(self.termination, DiagnosticFailure.DEADLINE)
            )
            for task in self.planned.values():
                if task.id not in self.observations:
                    self.publish(_cancelled(task, reason))
        if self.termination is DiagnosticTermination.COMPLETED and any(
            o.failure_code is DiagnosticFailure.DEADLINE for o in self.observations.values()
        ):
            self.termination = DiagnosticTermination.DEADLINE


def failed_target_ids(report: DiagnosticReport, targets) -> frozenset[str]:
    """Цели для разбора причин: прямой HTTP по IPv4 без единого успеха."""
    known = {t.id: t for t in targets}
    helpers = (DiagnosticPurpose.BASELINE, DiagnosticPurpose.CONTROL)
    groups: dict[str, list[ProbeObservation]] = {}
    for item in report.observations:
        target = known.get(item.target_id)
        if (
            target is not None
            and (target.purpose in helpers or target.purpose in SERVICE_PURPOSES)
            and item.route is ProbeRoute.DIRECT
            and item.stage is ProbeStage.HTTP
            and item.address_family is AddressFamily.IPV4
        ):
            groups.setdefault(item.target_id, []).append(item)
    failed = [
        target_id
        for target_id, items in groups.items()
        if not any(o.status is ProbeStatus.SUCCESS for o in items)
        and any(
            o.status in (ProbeStatus.FAILURE, ProbeStatus.INCONCLUSIVE, ProbeStatus.SKIPPED)
            for o in items
        )
    ]
    return frozenset(failed[:MAX_DETAIL_TARGETS])


def causes_request(failed: frozenset[str]) -> DiagnosticRequest:
    """Отдельный запуск: исчерпанный срок разбора не делает основной отчёт неполным."""
    return DiagnosticRequest(
        section=DiagnosticSection.DETAILS,
        detail_target_ids=failed,
        deadline_ms=CAUSES_DEADLINE_MS,
        compare_active_tunnel=False,
    )


def same_network(main: DiagnosticReport, causes: DiagnosticReport) -> bool:
    if causes.termination in (
        DiagnosticTermination.NETWORK_CHANGED,
        DiagnosticTermination.INTERNAL_ERROR,
    ):
        return False
    first, second = main.network_facts(), causes.network_facts()
    return (first.type if first else None) == (second.type if second else None)


def detected_policy() -> DirectPolicy:
    """Для CLI: настроек сеанса нет, туннель определяется по маршруту."""
    return DirectPolicy(tun_interface=netbind.active_tunnel_interface())


def context_sources(context) -> DiagnosticSources:
    """Источники GUI: что запущено, читается из AppContext при каждом опросе."""

    def policy() -> DirectPolicy:
        state = context.proxy_state
        settings = getattr(context, "config", None)
        tun = state.is_running and state.started_mode == "tun"
        name = (getattr(settings, "tun_name", "") or "xray0").strip() if tun else None
        kill_switch = state.traffic_blocked or (
            tun and getattr(settings, "tun_kill_switch", False) is True
        )
        return DirectPolicy(tun_interface=name, kill_switch=kill_switch)

    return DiagnosticSources(policy, lambda: context.proxy_state.health_endpoint)


def desktop_runner(sources: DiagnosticSources, app_version: str) -> DiagnosticRunner:
    return DiagnosticRunner(lambda request: DesktopEnvironment(request, sources), app_version)
