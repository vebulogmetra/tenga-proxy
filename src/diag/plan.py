"""План проб по фазам: порт DiagnosticProbePlan.kt.

Состав следующей фазы зависит от наблюдений предыдущей (повторы только успешных и отказавших
попыток, третья попытка при расхождении), поэтому план — объект с состоянием, а не готовый
список. Адреса из DNS хранятся только здесь и в отчёт не попадают.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Protocol

from src.diag.assess.allowlist import needs_tie_break
from src.diag.catalog import (
    DiagnosticCatalog,
    DiagnosticPurpose,
    DiagnosticTarget,
    PlacementRegistry,
)
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    DiagnosticRequest,
    DiagnosticSection,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.probes.limits import MEDIA_BYTES, TELEGRAM_PAGE_BYTES, YOUTUBE_PAGE_BYTES
from src.diag.scheduler import DiagnosticTask

DETAIL_CONTROLS = frozenset({"google-web", "cloudflare-trace", "yandex-main"})
DNS_RESOLVERS = ("system", "cloudflare-doh", "google-doh")
MAX_PLANNED = 1024
DNS_RESERVE = 16_656
TELEGRAM_APP_RESERVE = 4_137


class DnsResult(Protocol):
    observation: ProbeObservation
    addresses: tuple[str, ...]


class ProbeBackend(Protocol):
    """Сеть плана: на десктопе — сокеты, привязанные к интерфейсу, и health-inbound сеанса."""

    def extended_tasks(self) -> list[DiagnosticTask]: ...

    def baseline(self) -> ProbeObservation: ...

    def dns(
        self, id: str, target: DiagnosticTarget, family: AddressFamily, resolver: str
    ) -> DnsResult: ...

    def connection(
        self,
        id: str,
        target: DiagnosticTarget,
        stage: ProbeStage,
        route: ProbeRoute,
        address: str | None,
    ) -> ProbeObservation: ...


def with_changes(observation: ProbeObservation, **changes) -> ProbeObservation:
    fields = {
        "id": observation.id,
        "target_id": observation.target_id,
        "route": observation.route,
        "stage": observation.stage,
        "status": observation.status,
        "attempt": observation.attempt,
        "elapsed_ms": observation.elapsed_ms,
        "failure_code": observation.failure_code,
        "address_family": observation.address_family,
        "http_status": observation.http_status,
        "evidence": observation.evidence,
    }
    fields.update(changes)
    return ProbeObservation(**fields)


def _family_id(family: AddressFamily) -> str:
    return family.name.lower()


class DiagnosticProbePlan:
    def __init__(
        self,
        catalog: DiagnosticCatalog,
        request: DiagnosticRequest,
        backend: ProbeBackend,
        placements: PlacementRegistry | None = None,
        epoch_seconds: Callable[[], float] = time.time,
    ):
        self.catalog = catalog
        self._request = request
        self._backend = backend
        self._placements = placements or PlacementRegistry.empty()
        self._epoch_seconds = epoch_seconds
        self.allowlist_complete = False
        self.services_started = request.section is DiagnosticSection.SERVICES
        self.services_complete = False
        self.dns_started = request.section is DiagnosticSection.DNS
        self.dns_complete = False
        self._lock = threading.Lock()
        self._answers: dict[tuple[str, AddressFamily, str], tuple[str, str]] = {}
        self._ipv4_answers: dict[str, set[str]] = {}
        self._baseline = [
            t
            for t in catalog.targets
            if t.purpose in (DiagnosticPurpose.BASELINE, DiagnosticPurpose.CONTROL)
        ]
        self._services = [t for t in catalog.targets if t not in self._baseline]
        # Российский контроль отличает фильтр по имени от общего отказа TLS: при белых
        # списках зарубежные контрольные цели тоже не отвечают.
        self._detail_targets = [
            t
            for t in catalog.targets
            if (t.id in request.detail_target_ids or t.id in DETAIL_CONTROLS)
            and AddressFamily.IPV4 in t.families
        ]

    @property
    def compare_services_through_tunnel(self) -> bool:
        return self._request.compare_active_tunnel

    @property
    def verified_placement_groups(self) -> frozenset[str]:
        return self._placements.groups(self._epoch_seconds())

    def phase_completed(self, phase: int) -> None:
        if phase == 3:
            self.allowlist_complete = True
            self.services_started = True
        if phase == 6:
            self.services_complete = True
            self.dns_started = True
        if phase == 7:
            self.dns_complete = True

    def tasks(
        self, phase: int, observations: list[ProbeObservation]
    ) -> list[DiagnosticTask] | None:
        if not 0 <= phase <= 8:
            return None
        if phase not in self._request.phases:
            return []
        builders: Mapping[int, Callable[[], list[DiagnosticTask]]] = {
            0: self._phase_baseline,
            1: lambda: self._dns_tasks(self._dns_scope(self._baseline)),
            2: lambda: self._connections(self._baseline),
            3: lambda: self._repeat_baseline(observations),
            4: lambda: self._dns_tasks(self._dns_scope(self._services)),
            5: self._phase_services,
            6: lambda: self._service_http(attempt=2),
            7: self._phase_dns,
            8: self._detail_connections,
        }
        return builders[phase]()

    def follow_up_tasks(
        self, phase: int, observations: list[ProbeObservation]
    ) -> list[DiagnosticTask]:
        section = self._request.section
        if phase == 3 and section in (None, DiagnosticSection.ALLOWLIST):
            return [
                self._connection(target, AddressFamily.IPV4, ProbeStage.HTTP, 3)
                for target in self._baseline
                if target.purpose is DiagnosticPurpose.BASELINE
                and needs_tie_break([o for o in observations if o.target_id == target.id])
            ]
        if phase == 7 and section in (None, DiagnosticSection.DNS):
            return self._consistency_tasks()
        return []

    def _phase_baseline(self) -> list[DiagnosticTask]:
        tasks = [
            DiagnosticTask(
                "network", "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, 0,
                self._backend.baseline,
            )
        ]  # fmt: skip
        if self._request.section is None:
            tasks.append(
                DiagnosticTask(
                    "portal", "portal", "portal", ProbeRoute.DIRECT, ProbeStage.HTTP, 0,
                    _http_portal,
                )
            )  # fmt: skip
        return tasks

    def _dns_scope(self, targets: list[DiagnosticTarget]) -> list[DiagnosticTarget]:
        if self._request.section is DiagnosticSection.DETAILS:
            return [t for t in self._detail_targets if t in targets]
        return targets

    def _repeat_baseline(self, observations: list[ProbeObservation]) -> list[DiagnosticTask]:
        baseline = {t.id for t in self._baseline if t.purpose is DiagnosticPurpose.BASELINE}
        tasks = []
        for previous in observations:
            if (
                previous.route is ProbeRoute.DIRECT
                and previous.address_family is AddressFamily.IPV4
                and previous.stage is ProbeStage.HTTP
                and previous.attempt == 1
                and previous.target_id in baseline
                and previous.status in (ProbeStatus.SUCCESS, ProbeStatus.FAILURE)
            ):
                target = self.catalog.target(previous.target_id)
                tasks.append(self._connection(target, previous.address_family, ProbeStage.HTTP, 2))
        return tasks

    def _phase_services(self) -> list[DiagnosticTask]:
        tasks = self._service_http(attempt=1)
        if self._request.compare_active_tunnel:
            tasks.extend(self._tunnel_task(target) for target in self._services)
        return tasks

    def _tunnel_task(self, target: DiagnosticTarget) -> DiagnosticTask:
        task_id = f"{target.id}-tunnel"
        return DiagnosticTask(
            task_id,
            target.id,
            target.hostname,
            ProbeRoute.ACTIVE_TUNNEL,
            ProbeStage.HTTP,
            self._payload(target, ProbeStage.HTTP),
            lambda: self._backend.connection(
                task_id, target, ProbeStage.HTTP, ProbeRoute.ACTIVE_TUNNEL, None
            ),
        )

    def _service_http(self, attempt: int) -> list[DiagnosticTask]:
        return [
            self._connection(target, family, ProbeStage.HTTP, attempt)
            for target in self._services
            for family in self._probe_families(target)
        ]

    def _phase_dns(self) -> list[DiagnosticTask]:
        tasks = []
        for target in self.catalog.dns_targets():
            if AddressFamily.IPV4 in self._probe_families(target):
                tasks.append(self._system_dns_repeat(target))
        tasks.extend(
            task
            for task in self._backend.extended_tasks()
            if task.route is ProbeRoute.DIRECT and task.stage in (ProbeStage.UDP, ProbeStage.TCP)
        )
        return tasks

    def _system_dns_repeat(self, target: DiagnosticTarget) -> DiagnosticTask:
        task_id = f"{target.id}-ipv4-dns-system-2"

        def execute() -> ProbeObservation:
            result = self._backend.dns(task_id, target, AddressFamily.IPV4, "system")
            self._remember(target, AddressFamily.IPV4, "system", result)
            return with_changes(result.observation, attempt=2)

        return DiagnosticTask(
            task_id, target.id, target.hostname, ProbeRoute.DIRECT, ProbeStage.DNS, DNS_RESERVE,
            execute,
        )  # fmt: skip

    def _consistency_tasks(self) -> list[DiagnosticTask]:
        # Без ключа resolver в evidence: иначе оценка DNS примет задачу за системный запрос.
        targets = [
            t for t in self.catalog.dns_targets() if AddressFamily.IPV4 in self._probe_families(t)
        ]
        return [self._consistency_task(target, targets) for target in targets]

    def _consistency_task(
        self, target: DiagnosticTarget, targets: list[DiagnosticTarget]
    ) -> DiagnosticTask:
        task_id = f"{target.id}-ipv4-dns-consistency"

        def execute() -> ProbeObservation:
            system = self._answers_of(target.id, "system")
            doh = self._answers_of(target.id, "doh")
            if not system or not doh:
                overlap = "unknown"
            elif not system & doh:
                overlap = "none"
            elif system <= doh:
                overlap = "full"
            else:
                overlap = "partial"
            # Один IP у разных владельцев, которого нет в DoH: заглушка оператора.
            shared = any(
                other.placement_group != target.placement_group
                and any(
                    ip in system and ip not in doh and ip not in self._answers_of(other.id, "doh")
                    for ip in self._answers_of(other.id, "system")
                )
                for other in targets
            )
            return ProbeObservation(
                task_id,
                target.id,
                ProbeRoute.DIRECT,
                ProbeStage.DNS,
                ProbeStatus.INCONCLUSIVE if overlap == "unknown" else ProbeStatus.SUCCESS,
                address_family=AddressFamily.IPV4,
                evidence={
                    "coverage": "answer-consistency",
                    "dohOverlap": overlap,
                    "sharedAnswer": str(shared).lower(),
                },
            )

        return DiagnosticTask(
            task_id, target.id, "dns-consistency", ProbeRoute.DIRECT, ProbeStage.DNS, 0, execute
        )

    def _answers_of(self, target_id: str, source: str) -> frozenset[str]:
        with self._lock:
            return frozenset(self._ipv4_answers.get(f"{target_id}:{source}", ()))

    def _detail_connections(self) -> list[DiagnosticTask]:
        return [
            self._connection(target, AddressFamily.IPV4, stage, attempt)
            for target in self._detail_targets
            for stage in (ProbeStage.TCP, ProbeStage.TLS)
            for attempt in (1, 2)
        ]

    def _probe_families(self, target: DiagnosticTarget) -> list[AddressFamily]:
        return [
            family
            for family in target.families
            if (
                target.purpose is not DiagnosticPurpose.BASELINE
                and self._request.section is not DiagnosticSection.DETAILS
            )
            or family is AddressFamily.IPV4
        ]

    def _dns_tasks(self, targets: list[DiagnosticTarget]) -> list[DiagnosticTask]:
        return [
            self._dns_task(target, family, resolver)
            for target in targets
            for family in self._probe_families(target)
            for resolver in DNS_RESOLVERS
        ]

    def _dns_task(
        self, target: DiagnosticTarget, family: AddressFamily, resolver: str
    ) -> DiagnosticTask:
        task_id = f"{target.id}-{_family_id(family)}-dns-{resolver}"

        def execute() -> ProbeObservation:
            result = self._backend.dns(task_id, target, family, resolver)
            self._remember(target, family, resolver, result)
            if result.observation.status is ProbeStatus.SUCCESS and result.addresses:
                with self._lock:
                    self._answers[(target.id, family, resolver)] = (result.addresses[0], resolver)
            return result.observation

        origin = target.hostname if resolver == "system" else resolver
        return DiagnosticTask(
            task_id, target.id, origin, ProbeRoute.DIRECT, ProbeStage.DNS, DNS_RESERVE, execute
        )

    def _remember(
        self, target: DiagnosticTarget, family: AddressFamily, resolver: str, result: DnsResult
    ) -> None:
        if family is not AddressFamily.IPV4 or result.observation.status is not ProbeStatus.SUCCESS:
            return
        source = "system" if resolver == "system" else "doh"
        with self._lock:
            self._ipv4_answers.setdefault(f"{target.id}:{source}", set()).update(result.addresses)

    def _connections(self, targets: list[DiagnosticTarget]) -> list[DiagnosticTask]:
        return [
            self._connection(target, family, stage, 1)
            for target in targets
            for family in self._probe_families(target)
            for stage in (ProbeStage.TCP, ProbeStage.TLS, ProbeStage.HTTP)
        ]

    def _connection(
        self, target: DiagnosticTarget, family: AddressFamily, stage: ProbeStage, attempt: int
    ) -> DiagnosticTask:
        task_id = f"{target.id}-{_family_id(family)}-{stage.name.lower()}-{attempt}"

        def execute() -> ProbeObservation:
            resolved = self._resolved(target, family)
            if resolved is None:
                return ProbeObservation(
                    task_id,
                    target.id,
                    ProbeRoute.DIRECT,
                    stage,
                    ProbeStatus.SKIPPED,
                    attempt=attempt,
                    address_family=family,
                    failure_code=DiagnosticFailure.DNS_FAILED,
                )
            address, resolver = resolved
            observed = self._backend.connection(task_id, target, stage, ProbeRoute.DIRECT, address)
            group = self._placements.group(target, address, self._epoch_seconds())
            evidence = {k: v for k, v in observed.evidence.items() if k != "placementGroup"}
            evidence["resolver"] = resolver
            if group is not None:
                evidence["placementGroup"] = group
            return with_changes(observed, attempt=attempt, address_family=family, evidence=evidence)

        return DiagnosticTask(
            task_id,
            target.id,
            target.hostname,
            ProbeRoute.DIRECT,
            stage,
            self._payload(target, stage),
            execute,
        )

    def _resolved(self, target: DiagnosticTarget, family: AddressFamily) -> tuple[str, str] | None:
        with self._lock:
            for resolver in DNS_RESOLVERS:
                found = self._answers.get((target.id, family, resolver))
                if found is not None:
                    return found
        return None

    @staticmethod
    def _payload(target: DiagnosticTarget, stage: ProbeStage) -> int:
        if stage is not ProbeStage.HTTP:
            return 0
        if target.purpose is DiagnosticPurpose.TELEGRAM_APP:
            return TELEGRAM_APP_RESERVE
        if target.purpose is DiagnosticPurpose.TELEGRAM_MEDIA:
            return TELEGRAM_PAGE_BYTES + MEDIA_BYTES
        if target.purpose is DiagnosticPurpose.YOUTUBE_VIDEO:
            return YOUTUBE_PAGE_BYTES + MEDIA_BYTES
        return target.max_bytes + 1


def _http_portal() -> ProbeObservation:
    # Своего HTTP-контроля нет, как и на Android: страницу входа не определяем.
    return ProbeObservation(
        "portal",
        "portal",
        ProbeRoute.DIRECT,
        ProbeStage.HTTP,
        ProbeStatus.UNSUPPORTED,
        failure_code=DiagnosticFailure.CONTROL_UNAVAILABLE,
    )
