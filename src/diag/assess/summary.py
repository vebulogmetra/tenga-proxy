"""Общий вывод карточки: порт DiagnosticSummary.kt."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from src.diag.catalog import DiagnosticPurpose as P
from src.diag.models import (
    AllowlistAssessment,
    AllowlistVerdict,
    DnsAssessment,
    DnsVerdict,
    ProbeRoute,
    ServiceAssessment,
    ServiceCheckStatus,
)


class SummaryVerdict(enum.Enum):
    MIXED_NETWORKS = "MIXED_NETWORKS"
    NO_ACCESS = "NO_ACCESS"
    ALLOWLIST = "ALLOWLIST"
    PARTIAL_RESOURCES = "PARTIAL_RESOURCES"
    SERVICES_BLOCKED = "SERVICES_BLOCKED"
    SOME_SERVICES_BLOCKED = "SOME_SERVICES_BLOCKED"
    DNS_PROBLEM = "DNS_PROBLEM"
    ALL_AVAILABLE = "ALL_AVAILABLE"
    UNKNOWN = "UNKNOWN"


# Названия — единственные подписи сервисов на экране; у каждого по две функции.
SERVICES = (
    ("Telegram", frozenset({P.TELEGRAM_WEB, P.TELEGRAM_MEDIA})),
    ("Instagram", frozenset({P.INSTAGRAM_WEB, P.INSTAGRAM_MEDIA})),
    ("YouTube", frozenset({P.YOUTUBE_WEB, P.YOUTUBE_VIDEO})),
)
_DNS_PROBLEMS = frozenset(
    {
        DnsVerdict.SPOOFING,
        DnsVerdict.INTERCEPTION,
        DnsVerdict.DOMAINS_HIDDEN,
        DnsVerdict.SYSTEM_NOT_RESPONDING,
    }
)


@dataclass(frozen=True)
class DiagnosticSummary:
    verdict: SummaryVerdict
    blocked_services: tuple[str, ...]
    dns_verdict: DnsVerdict | None
    incomplete: bool


def summarize(
    allowlist: AllowlistAssessment | None,
    services: ServiceAssessment | None,
    dns: DnsAssessment | None,
    network_types,
    partial: bool,
) -> DiagnosticSummary:
    direct = ()
    if services is not None and services.completed:
        for route in services.routes:
            if route.route is ProbeRoute.DIRECT:
                direct = route.checks
                break
    blocked = tuple(
        name
        for name, purposes in SERVICES
        if any(c.purpose in purposes and c.status is ServiceCheckStatus.UNAVAILABLE for c in direct)
    )
    allowlist_verdict = allowlist.verdict if allowlist else None
    dns_verdict = dns.verdict if dns else None
    if len({t for t in network_types if t is not None}) > 1:
        verdict = SummaryVerdict.MIXED_NETWORKS
    elif allowlist_verdict is AllowlistVerdict.NO_ACCESS:
        verdict = SummaryVerdict.NO_ACCESS
    elif allowlist_verdict is AllowlistVerdict.POSSIBLE:
        verdict = SummaryVerdict.ALLOWLIST
    elif allowlist_verdict is AllowlistVerdict.PARTIAL_RESTRICTIONS:
        verdict = SummaryVerdict.PARTIAL_RESOURCES
    elif direct and all(c.status is ServiceCheckStatus.UNAVAILABLE for c in direct):
        verdict = SummaryVerdict.SERVICES_BLOCKED
    elif blocked:
        verdict = SummaryVerdict.SOME_SERVICES_BLOCKED
    elif dns_verdict in _DNS_PROBLEMS:
        verdict = SummaryVerdict.DNS_PROBLEM
    elif (
        allowlist_verdict is AllowlistVerdict.NO_PATTERN
        and direct
        and all(c.status is ServiceCheckStatus.AVAILABLE for c in direct)
        and dns_verdict in (DnsVerdict.WORKING, DnsVerdict.WORKING_DOH_BLOCKED)
    ):
        verdict = SummaryVerdict.ALL_AVAILABLE
    else:
        verdict = SummaryVerdict.UNKNOWN
    return DiagnosticSummary(verdict, blocked, dns_verdict, partial)
