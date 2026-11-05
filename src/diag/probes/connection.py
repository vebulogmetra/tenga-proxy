"""TCP- и TLS-пробы для разбора причин: порт TcpProbe.kt и TlsProbe.kt."""

from __future__ import annotations

import time

from src.diag.catalog import DiagnosticTarget
from src.diag.models import ProbeObservation, ProbeRoute, ProbeStage, ProbeStatus
from src.diag.probes.https import address_problem, family_of
from src.diag.probes.support import ProbeContext, classify, elapsed_since, status_of


def probe_tcp(
    context: ProbeContext, id: str, target: DiagnosticTarget, address: str, timeout: float
) -> ProbeObservation:
    return _probe(context, id, target, address, timeout, ProbeStage.TCP)


def probe_tls(
    context: ProbeContext, id: str, target: DiagnosticTarget, address: str, timeout: float
) -> ProbeObservation:
    return _probe(context, id, target, address, timeout, ProbeStage.TLS)


def _probe(context, id, target, address, timeout, stage) -> ProbeObservation:
    started = time.monotonic()

    def result(status, failure=None, evidence=None) -> ProbeObservation:
        return ProbeObservation(
            id, target.id, ProbeRoute.DIRECT, stage, status,
            elapsed_ms=elapsed_since(started), failure_code=failure,
            address_family=family_of(address), evidence=evidence or {},
        )  # fmt: skip

    problem = address_problem(address, target)
    if problem:
        return result(*problem)
    sock = None
    try:
        sock = context.connect(address, target.port, timeout)
        if stage is ProbeStage.TCP:
            return result(ProbeStatus.SUCCESS)
        sock.settimeout(max(0.001, timeout - (time.monotonic() - started)))
        sock = context.wrap_tls(sock, target.hostname)
        return result(ProbeStatus.SUCCESS, evidence={"tlsVersion": sock.version() or "unknown"})
    except OSError as error:
        failure = classify(error, under_tun=context.under_tun)
        return result(status_of(failure), failure)
    finally:
        if sock is not None:
            context.release(sock)
