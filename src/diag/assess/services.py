"""Оценка сервисов: порт DiagnosticServiceAssessor.kt.

Доступность функции отделена и от причины отказа, и от полной работы приложения.
"""

from __future__ import annotations

from src.diag.assess.allowlist import is_network_failure
from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose
from src.diag.models import (
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
    ServiceAssessment,
    ServiceCheck,
    ServiceCheckStatus,
    ServiceRoute,
)

PURPOSES = frozenset(
    {
        DiagnosticPurpose.TELEGRAM_WEB,
        DiagnosticPurpose.TELEGRAM_MEDIA,
        DiagnosticPurpose.INSTAGRAM_WEB,
        DiagnosticPurpose.INSTAGRAM_MEDIA,
        DiagnosticPurpose.YOUTUBE_WEB,
        DiagnosticPurpose.YOUTUBE_VIDEO,
    }
)


def assess_services(
    catalog: DiagnosticCatalog,
    observations: list[ProbeObservation] | tuple[ProbeObservation, ...],
    *,
    started: bool,
    completed: bool,
    compare_tunnel: bool,
    network_changed: bool = False,
    tunnel_changed: bool = False,
) -> ServiceAssessment:
    targets = [t for t in catalog.targets if t.purpose in PURPOSES]
    routes = [ProbeRoute.DIRECT] + ([ProbeRoute.ACTIVE_TUNNEL] if compare_tunnel else [])
    # Идентификаторы совпадают с планом, включая пропуски и отмены без семейства адресов.
    planned: set[str] = set()
    for target in targets:
        for family in target.families:
            planned.update(f"{target.id}-{family.name.lower()}-http-{a}" for a in (1, 2))
        if compare_tunnel:
            planned.add(f"{target.id}-tunnel")
    checked = sum(o.id in planned for o in observations)
    results = tuple(
        ServiceRoute(
            route,
            tuple(
                _check(target, route, observations, network_changed, tunnel_changed)
                for target in targets
            ),
        )
        for route in routes
    )
    return ServiceAssessment(started, completed, checked, len(planned), results)


def _check(target, route, observations, network_changed, tunnel_changed) -> ServiceCheck:
    items = [
        o
        for o in observations
        if o.target_id == target.id and o.route is route and o.stage is ProbeStage.HTTP
    ]
    successes = [
        o
        for o in items
        if o.status is ProbeStatus.SUCCESS and o.evidence.get("coverage") != "web-challenge"
    ]
    failures = [o for o in items if is_network_failure(o)]
    by_family: dict = {}
    for item in failures:
        by_family.setdefault(item.address_family, []).append(item)
    repeated = any(
        all(any(i.attempt == attempt for i in attempts) for attempt in (1, 2))
        for attempts in by_family.values()
    )
    dns = [
        o
        for o in observations
        if o.target_id == target.id and o.route is route and o.stage is ProbeStage.DNS
    ]
    dns_failure = (
        bool(items)
        and all(
            o.status is ProbeStatus.SKIPPED and o.failure_code is DiagnosticFailure.DNS_FAILED
            for o in items
        )
        and len(dns) >= 3
        and all(is_network_failure(o) for o in dns)
    )
    changed = network_changed or (route is ProbeRoute.ACTIVE_TUNNEL and tunnel_changed)
    if changed:
        state = ServiceCheckStatus.UNKNOWN
    elif successes and (
        failures
        or dns_failure
        or any(o.status is ProbeStatus.INCONCLUSIVE or o.http_status in (403, 429) for o in items)
    ):
        state = ServiceCheckStatus.PARTIAL
    elif successes:
        state = ServiceCheckStatus.AVAILABLE
    elif repeated or dns_failure:
        state = ServiceCheckStatus.UNAVAILABLE
    elif not items:
        state = ServiceCheckStatus.NOT_CHECKED
    else:
        state = ServiceCheckStatus.UNKNOWN
    problem = (
        next(iter(failures), None)
        or next(
            (o for o in items if o.status not in (ProbeStatus.SUCCESS, ProbeStatus.CANCELLED)),
            None,
        )
        or next((o for o in items if o.status is not ProbeStatus.SUCCESS), None)
    )
    failure = problem.failure_code if problem else None
    if network_changed:
        failure = DiagnosticFailure.NETWORK_CHANGED
    elif route is ProbeRoute.ACTIVE_TUNNEL and tunnel_changed:
        failure = DiagnosticFailure.VPN_SESSION_CHANGED
    elif failure is DiagnosticFailure.DNS_FAILED and any(
        o.failure_code is DiagnosticFailure.UNSAFE_ADDRESS for o in dns
    ):
        failure = DiagnosticFailure.UNSAFE_ADDRESS
    if route is ProbeRoute.ACTIVE_TUNNEL:
        done = bool(items)
    else:
        ids = {o.id for o in items}
        done = all(
            f"{target.id}-{family.name.lower()}-http-{attempt}" in ids
            for family in target.families
            for attempt in (1, 2)
        )
    return ServiceCheck(
        target.id,
        target.purpose,
        state,
        failure,
        problem.http_status if problem else None,
        problem.evidence.get("mediaDetail") if problem else None,
        done,
    )
