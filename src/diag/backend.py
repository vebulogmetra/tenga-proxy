"""Сеть плана на десктопе: порт backend из AndroidDiagnosticEnvironmentFactory.kt."""

from __future__ import annotations

import time
from collections.abc import Callable

from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.network import NetworkState
from src.diag.probes import dns as dns_probes
from src.diag.probes.connection import probe_tcp, probe_tls
from src.diag.probes.dns import DnsProbeResult
from src.diag.probes.https import probe_https
from src.diag.probes.limits import (
    CONNECTION_TIMEOUT_S,
    DOH_TIMEOUT_S,
    SYSTEM_DNS_TIMEOUT_S,
    http_timeout_s,
)
from src.diag.probes.media import probe_media
from src.diag.probes.support import ProbeContext
from src.diag.probes.telegram import probe_telegram
from src.diag.scheduler import DiagnosticTask
from src.diag.session import TunnelSession, TunnelSessionSource

_RESOLVERS = ("cloudflare-dns", "google-dns")
_TRANSPORT_RESERVE = 4352
_INTERCEPTION_RESERVE = 512


class DesktopProbeBackend:
    def __init__(
        self,
        network: NetworkState,
        direct: ProbeContext,
        tunnel: ProbeContext,
        sessions: TunnelSessionSource,
        session: TunnelSession | None,
        *,
        compare_tunnel: bool,
        dns_servers: Callable[[], list[str]],
        epoch_seconds: Callable[[], float] = time.time,
    ):
        self._network = network
        self._direct = direct
        self._tunnel = tunnel
        self._sessions = sessions
        self._session = session
        self._compare_tunnel = compare_tunnel
        self._dns_servers = dns_servers
        self._epoch_seconds = epoch_seconds

    def _restricted(self, id, target_id, stage, route=ProbeRoute.DIRECT, family=None):
        return ProbeObservation(
            id, target_id, route, stage, ProbeStatus.SKIPPED,
            failure_code=DiagnosticFailure.SYSTEM_RESTRICTED, address_family=family,
        )  # fmt: skip

    def baseline(self) -> ProbeObservation:
        if not self._network.available:
            return ProbeObservation(
                "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK,
                ProbeStatus.INCONCLUSIVE, failure_code=DiagnosticFailure.NO_NETWORK,
            )  # fmt: skip
        return ProbeObservation(
            "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS,
            evidence={
                "networkType": self._network.kind,
                "vpnActive": str(self._network.under_tun or self._session is not None).lower(),
                "privateDns": "unknown",
            },
        )  # fmt: skip

    def dns(
        self, id: str, target: DiagnosticTarget, family: AddressFamily, resolver: str
    ) -> DnsProbeResult:
        if self._network.restricted:
            return DnsProbeResult(self._restricted(id, target.id, ProbeStage.DNS, family=family))
        if resolver == "system":
            return dns_probes.probe_system_dns(
                self._direct, id, target.id, target.hostname, family, self._dns_servers,
                SYSTEM_DNS_TIMEOUT_S,
            )  # fmt: skip
        known = next((e for e in dns_probes.DOH_ENDPOINTS if e.id == resolver), None)
        endpoint = known.for_family(self._network.transport_family) if known else None
        if endpoint is None:
            return DnsProbeResult(
                ProbeObservation(
                    id, target.id, ProbeRoute.DIRECT, ProbeStage.DNS, ProbeStatus.UNSUPPORTED,
                    address_family=family, failure_code=DiagnosticFailure.CONTROL_UNAVAILABLE,
                )
            )  # fmt: skip
        return dns_probes.probe_doh(
            self._direct, id, target.id, target.hostname, family, endpoint,
            self._epoch_seconds(), DOH_TIMEOUT_S,
        )  # fmt: skip

    def connection(
        self,
        id: str,
        target: DiagnosticTarget,
        stage: ProbeStage,
        route: ProbeRoute,
        address: str | None,
    ) -> ProbeObservation:
        def unavailable(reason, status) -> ProbeObservation:
            return ProbeObservation(id, target.id, route, stage, status, failure_code=reason)

        if route is ProbeRoute.DIRECT:
            if self._network.restricted:
                return self._restricted(id, target.id, stage)
            return self._execute(self._direct, id, target, stage, route, address, None)
        session = self._session
        if session is None:
            return unavailable(DiagnosticFailure.PROXY_UNAVAILABLE, ProbeStatus.SKIPPED)
        if not self._sessions.is_current(session):
            return unavailable(DiagnosticFailure.VPN_SESSION_CHANGED, ProbeStatus.CANCELLED)
        observation = self._execute(self._tunnel, id, target, stage, route, None, session.endpoint)
        if not self._sessions.is_current(session):
            return unavailable(DiagnosticFailure.VPN_SESSION_CHANGED, ProbeStatus.CANCELLED)
        return observation

    def _execute(self, context, id, target, stage, route, address, proxy) -> ProbeObservation:
        if stage is ProbeStage.TCP:
            return probe_tcp(context, id, target, address, CONNECTION_TIMEOUT_S)
        if stage is ProbeStage.TLS:
            return probe_tls(context, id, target, address, CONNECTION_TIMEOUT_S)
        if stage is not ProbeStage.HTTP:
            return ProbeObservation(
                id, target.id, route, stage, ProbeStatus.UNSUPPORTED,
                failure_code=DiagnosticFailure.NOT_IMPLEMENTED,
            )  # fmt: skip
        if target.purpose is DiagnosticPurpose.TELEGRAM_APP:
            return probe_telegram(
                context, id, target, route, http_timeout_s(ProbeRoute.DIRECT), address, proxy
            )
        if target.purpose in (DiagnosticPurpose.TELEGRAM_MEDIA, DiagnosticPurpose.YOUTUBE_VIDEO):
            return probe_media(context, id, target, route, address, self._resolve_media, proxy)
        return probe_https(context, id, target, route, http_timeout_s(route), address, proxy)

    def _resolve_media(self, hostname: str, family: AddressFamily) -> tuple[str, ...]:
        result = dns_probes.probe_system_dns(
            self._direct, "media-dns", "media", hostname, family, self._dns_servers,
            SYSTEM_DNS_TIMEOUT_S,
        )  # fmt: skip
        return result.addresses

    def extended_tasks(self) -> list[DiagnosticTask]:
        family = self._network.transport_family
        tasks: list[DiagnosticTask] = []
        for resolver in _RESOLVERS:
            for stage, tcp in ((ProbeStage.UDP, False), (ProbeStage.TCP, True)):
                for attempt in (1, 2):
                    tasks.append(self._transport_task(resolver, stage, tcp, attempt, family))
        for resolver, task_id in (
            ("cloudflare-dns", "cloudflare-dns-identity"),
            ("google-dns", "google-dns-nxdomain"),
        ):
            tasks.append(self._interception_task(task_id, resolver, family))
        return tasks

    def _transport_task(self, resolver, stage, tcp, attempt, family) -> DiagnosticTask:
        task_id = f"{resolver}-{stage.name.lower()}-{attempt}"

        def execute() -> ProbeObservation:
            if self._network.restricted:
                return self._restricted(task_id, resolver, stage, family=family)
            observed = dns_probes.probe_dns_transport(
                self._direct, task_id, resolver, family, tcp=tcp
            )
            return ProbeObservation(
                observed.id, observed.target_id, observed.route, observed.stage, observed.status,
                attempt, observed.elapsed_ms, observed.failure_code, observed.address_family,
                observed.http_status, observed.evidence,
            )  # fmt: skip

        return DiagnosticTask(
            task_id, resolver, resolver, ProbeRoute.DIRECT, stage, _TRANSPORT_RESERVE, execute
        )

    def _interception_task(self, task_id, resolver, family) -> DiagnosticTask:
        def execute() -> ProbeObservation:
            if self._network.restricted:
                return self._restricted(task_id, resolver, ProbeStage.UDP, family=family)
            return dns_probes.probe_dns_interception(self._direct, task_id, resolver, family)

        return DiagnosticTask(
            task_id, resolver, resolver, ProbeRoute.DIRECT, ProbeStage.UDP,
            _INTERCEPTION_RESERVE, execute,
        )  # fmt: skip
