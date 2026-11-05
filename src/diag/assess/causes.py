"""Разбор причин: порт DiagnosticCauseAssessor.kt. Только наблюдённые этапы, без виновных."""

from __future__ import annotations

from collections.abc import Iterable

from src.diag.models import (
    AddressFamily,
    CauseAssessment,
    DiagnosticFailure,
    FailureCause,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)

_NETWORK_FAILURES = frozenset(
    {
        DiagnosticFailure.TIMEOUT,
        DiagnosticFailure.CONNECTION_REFUSED,
        DiagnosticFailure.CONNECTION_RESET,
        DiagnosticFailure.TLS_FAILED,
        DiagnosticFailure.IO,
    }
)


def _repeated_failure(items) -> bool:
    return all(
        any(
            o.attempt == attempt
            and o.status is ProbeStatus.FAILURE
            and o.failure_code in _NETWORK_FAILURES
            for o in items
        )
        for attempt in (1, 2)
    )


def assess_causes(observations, target_ids: Iterable[str]) -> CauseAssessment:
    ids = list(dict.fromkeys(target_ids))
    direct = [
        o
        for o in observations
        if o.route is ProbeRoute.DIRECT and o.address_family is AddressFamily.IPV4
    ]
    tcp: dict[str, list] = {}
    tls: dict[str, list] = {}
    for item in direct:
        if item.stage is ProbeStage.TCP:
            tcp.setdefault(item.target_id, []).append(item)
        elif item.stage is ProbeStage.TLS:
            tls.setdefault(item.target_id, []).append(item)
    causes: dict[str, FailureCause] = {}
    for target_id in ids:
        connect = tcp.get(target_id, [])
        secure = tls.get(target_id, [])
        # Если TLS не проходит ни у кого, это может быть общий отказ, а не фильтр по имени.
        other_passes = any(
            other != target_id and any(o.status is ProbeStatus.SUCCESS for o in items)
            for other, items in tls.items()
        )
        connected = any(o.status is ProbeStatus.SUCCESS for o in connect)
        if any(o.failure_code is DiagnosticFailure.TLS_CERTIFICATE for o in secure):
            causes[target_id] = FailureCause.CERTIFICATE
        elif _repeated_failure(connect):
            causes[target_id] = FailureCause.CONNECTION_FAILED
        elif connected and _repeated_failure(secure):
            causes[target_id] = (
                FailureCause.TLS_BLOCKED_BY_NAME if other_passes else FailureCause.TLS_FAILED
            )
        elif connected and secure and all(o.status is ProbeStatus.SUCCESS for o in secure):
            causes[target_id] = FailureCause.AFTER_HANDSHAKE
    return CauseAssessment(causes, len(ids))
