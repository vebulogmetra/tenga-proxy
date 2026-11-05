"""Текст для чата поддержки: порт DiagnosticSummaryText.kt.

Сами строки даёт интерфейс (`DiagnosticSummaryStrings`): здесь только порядок и подсчёт.
Текст содержит местное время, которого намеренно нет в JSON-отчёте.
"""

from __future__ import annotations

from typing import Protocol

from src.diag.assess.summary import SERVICES, DiagnosticSummary
from src.diag.models import (
    AddressFamily,
    AllowlistSiteState,
    AllowlistVerdict,
    DiagnosticNetworkFacts,
    DiagnosticReport,
    DiagnosticSection,
    DnsCheckStatus,
    DnsVerdict,
    FailureCause,
    ProbeRoute,
    ServiceCheckStatus,
)


class DiagnosticSummaryStrings(Protocol):
    def title(self, app_version: str, time: str) -> str: ...

    def network(self, facts: DiagnosticNetworkFacts | None) -> str: ...

    def verdict(self, summary: DiagnosticSummary) -> str: ...

    def allowlist(
        self, verdict: AllowlistVerdict, ru_ok: int, ru_total: int, other_ok: int, other_total: int
    ) -> str: ...

    def services(
        self, available: int, total: int, per_service: list[tuple[str, int, int]]
    ) -> str: ...

    def dns(
        self,
        verdict: DnsVerdict,
        system: tuple[int, int],
        public: tuple[int, int],
        secure: tuple[int, int],
    ) -> str: ...

    def causes(self, causes: tuple[FailureCause, ...], count: int, total: int) -> str: ...

    def state(self, incomplete: bool, section: DiagnosticSection | None, probes: int) -> str: ...


def build_summary_text(
    summary: DiagnosticSummary,
    report: DiagnosticReport,
    time: str,
    strings: DiagnosticSummaryStrings,
    *,
    cause_report: DiagnosticReport | None = None,
) -> str:
    """`cause_report` — отдельный запуск разбора причин после полной проверки."""
    lines = [
        strings.title(report.context.app_version, time),
        strings.network(report.network_facts()),
        strings.verdict(summary),
    ]
    allowlist = report.allowlist_assessment
    if allowlist is not None:
        sites = [site for family in allowlist.families for site in family.sites]
        russian = [s for s in sites if s.russian_reference]
        other = [s for s in sites if not s.russian_reference]

        def ok(items) -> int:
            return sum(s.state is AllowlistSiteState.AVAILABLE for s in items)

        lines.append(
            strings.allowlist(allowlist.verdict, ok(russian), len(russian), ok(other), len(other))
        )
    services = report.service_assessment
    if services is not None:
        direct = next((r for r in services.routes if r.route is ProbeRoute.DIRECT), None)
        if direct is not None:
            checks = direct.checks

            def available(items) -> int:
                return sum(c.status is ServiceCheckStatus.AVAILABLE for c in items)

            per_service = []
            for name, purposes in SERVICES:
                matching = [c for c in checks if c.purpose in purposes]
                if matching:
                    per_service.append((name, available(matching), len(matching)))
            lines.append(strings.services(available(checks), len(checks), per_service))
    dns = report.dns_assessment
    if dns is not None:

        def count(*resolvers) -> tuple[int, int]:
            # Только A, как в карточке DNS: строки AAAA лишь поясняют отказ A.
            items = [
                c
                for c in dns.checks
                if c.resolver in resolvers and c.family is not AddressFamily.IPV6
            ]
            return sum(c.status is DnsCheckStatus.AVAILABLE for c in items), len(items)

        lines.append(
            strings.dns(
                dns.verdict,
                count("system"),
                count("udp", "tcp", "identity", "nxdomain"),
                count("cloudflare-doh", "google-doh"),
            )
        )
    causes = cause_report.cause_assessment if cause_report else report.cause_assessment
    if causes is not None and causes.top_causes:
        lines.append(strings.causes(tuple(causes.top_causes), causes.top_cause_count, causes.total))
    # Повтор этапа считает свои пробы: причины прошлого запуска в нём не выполнялись.
    section = report.context.section
    probes = len(report.observations)
    if section is None and cause_report is not None:
        probes += len(cause_report.observations)
    lines.append(strings.state(summary.incomplete, section, probes))
    return "\n".join(lines)
