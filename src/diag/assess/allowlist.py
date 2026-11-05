"""Оценка белых списков: порт DiagnosticAllowlistAssessor.kt."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.diag.catalog import RUSSIAN_REFERENCES, DiagnosticCatalog, DiagnosticPurpose
from src.diag.models import (
    AddressFamily,
    AllowlistAssessment,
    AllowlistFamilyResult,
    AllowlistPolicy,
    AllowlistReason,
    AllowlistSiteResult,
    AllowlistSiteState,
    AllowlistVerdict,
    DiagnosticFailure,
    DiagnosticReport,
    DiagnosticTermination,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)

_NETWORK_FAILURES = frozenset(
    {
        DiagnosticFailure.DNS_FAILED,
        DiagnosticFailure.TIMEOUT,
        DiagnosticFailure.CONNECTION_REFUSED,
        DiagnosticFailure.CONNECTION_RESET,
        DiagnosticFailure.TLS_FAILED,
    }
)
_REJECTED_RESPONSES = frozenset(
    {
        DiagnosticFailure.TLS_CERTIFICATE,
        DiagnosticFailure.BODY_LIMIT,
        DiagnosticFailure.UNEXPECTED_RESPONSE,
        DiagnosticFailure.HTTP_REJECTED,
    }
)


@dataclass(frozen=True)
class ClassificationContext:
    now_epoch_seconds: float
    direct_context_stable: bool = False
    tunnel_comparison_valid: bool = False
    # Только из проверенного реестра размещений, а не из меток каталога.
    verified_placement_groups: frozenset[str] = frozenset()
    allowlist_policy: AllowlistPolicy = field(default_factory=AllowlistPolicy)


def is_network_failure(item: ProbeObservation) -> bool:
    return (
        item.status is ProbeStatus.FAILURE
        and item.http_status is None
        and item.failure_code in _NETWORK_FAILURES
    )


def needs_tie_break(items: list[ProbeObservation]) -> bool:
    if any(item.attempt == 3 for item in items):
        return False
    waves = [
        item
        for item in items
        if item.route is ProbeRoute.DIRECT
        and item.stage is ProbeStage.HTTP
        and item.address_family is AddressFamily.IPV4
        and item.attempt in (1, 2)
    ]
    return (
        {item.attempt for item in waves} == {1, 2}
        and sum(
            item.status is ProbeStatus.SUCCESS and item.evidence.get("responseMatched") == "true"
            for item in waves
        )
        == 1
        and sum(is_network_failure(item) for item in waves) == 1
    )


def _site_state(items, target, context, policy, all_dns_unavailable) -> AllowlistSiteState:
    if all_dns_unavailable:
        return AllowlistSiteState.UNAVAILABLE
    if not items:
        return AllowlistSiteState.NO_HTTP
    if any(
        (item.http_status is not None and item.status is not ProbeStatus.SUCCESS)
        or item.failure_code in _REJECTED_RESPONSES
        or item.evidence.get("coverage") == "web-challenge"
        for item in items
    ):
        return AllowlistSiteState.RESPONSE_REJECTED
    if target.placement_group not in context.verified_placement_groups or any(
        item.evidence.get("placementGroup") != target.placement_group for item in items
    ):
        return AllowlistSiteState.UNVERIFIED_PLACEMENT
    attempts = {item.attempt for item in items}
    if any(attempt not in attempts for attempt in range(1, policy.confirmations + 1)):
        return AllowlistSiteState.MISSING_REPEAT
    confirmed = {
        item.attempt
        for item in items
        if item.status is ProbeStatus.SUCCESS and item.evidence.get("responseMatched") == "true"
    }
    if len(confirmed) >= policy.confirmations:
        return AllowlistSiteState.AVAILABLE
    if all(is_network_failure(item) for item in items):
        return AllowlistSiteState.UNAVAILABLE
    return AllowlistSiteState.INCONSISTENT


def _run_reasons(report, catalog, context, direct, http) -> list[AllowlistReason]:
    reasons = []
    if report.termination is DiagnosticTermination.NETWORK_CHANGED or any(
        item.failure_code is DiagnosticFailure.NETWORK_CHANGED for item in direct
    ):
        reasons.append(AllowlistReason.NETWORK_CHANGED)
    elif not context.direct_context_stable or report.is_partial:
        reasons.append(AllowlistReason.INCOMPLETE_RUN)
    if catalog.expires_at <= context.now_epoch_seconds or report.context.catalog_version != str(
        catalog.catalog_version
    ):
        reasons.append(AllowlistReason.CATALOG_STALE)
    if any(item.failure_code is DiagnosticFailure.SYSTEM_RESTRICTED for item in direct):
        reasons.append(AllowlistReason.SYSTEM_RESTRICTED)
    if not http:
        reasons.append(AllowlistReason.NO_MEASUREMENTS)
    return reasons


def assess_allowlist(
    report: DiagnosticReport, catalog: DiagnosticCatalog, context: ClassificationContext
) -> AllowlistAssessment:
    policy = context.allowlist_policy
    targets = [t for t in catalog.targets if t.purpose is DiagnosticPurpose.BASELINE]
    target_ids = {t.id for t in targets}
    groups = {t.id: t.placement_group for t in targets}
    direct = [o for o in report.observations if o.route is ProbeRoute.DIRECT]
    http = [
        o
        for o in direct
        if o.stage is ProbeStage.HTTP
        and o.address_family is AddressFamily.IPV4
        and o.target_id in target_ids
    ]
    reasons = _run_reasons(report, catalog, context, direct, http)

    def dns_of(target_id: str) -> list[ProbeObservation]:
        return [
            o
            for o in direct
            if o.target_id == target_id
            and o.stage is ProbeStage.DNS
            and o.address_family is AddressFamily.IPV4
        ]

    # Полный отказ DNS мешает любой HTTP-попытке. Нужны независимые отказы резолверов
    # у каждой цели: пропущенный HTTP сам по себе ничего не доказывает.
    all_dns_unavailable = bool(targets) and all(
        len({o.id for o in dns_of(t.id)}) >= 3 and all(is_network_failure(o) for o in dns_of(t.id))
        for t in targets
    )
    evidence: list[str] = []
    family: AllowlistFamilyResult | None = None
    if any(o.address_family is AddressFamily.IPV4 and o.target_id in target_ids for o in direct):
        by_target: dict[str, list[ProbeObservation]] = {}
        for item in http:
            by_target.setdefault(item.target_id, []).append(item)
        sites = [
            AllowlistSiteResult(
                t.id,
                t.hostname,
                _site_state(by_target.get(t.id, []), t, context, policy, all_dns_unavailable),
                t.hostname in RUSSIAN_REFERENCES,
            )
            for t in targets
        ]
        good = [s for s in sites if s.state is AllowlistSiteState.AVAILABLE]
        good_groups = {groups[s.target_id] for s in good}
        final_sites = tuple(
            _shared(site) if _is_shared(site, groups, good_groups) else site for site in sites
        )
        bad = [s for s in final_sites if s.state is AllowlistSiteState.UNAVAILABLE]
        success_hosts = len({s.hostname for s in good})
        failed_hosts = len({s.hostname for s in bad})
        bad_groups = {groups[s.target_id] for s in bad}
        missing = []
        if success_hosts < policy.success_targets:
            missing.append(AllowlistReason.TOO_FEW_SUCCESSES)
        if len(good_groups) < policy.success_groups:
            missing.append(AllowlistReason.TOO_FEW_SUCCESS_GROUPS)
        if failed_hosts < policy.failed_targets:
            missing.append(AllowlistReason.TOO_FEW_FAILURES)
        if len(bad_groups) < policy.failed_groups:
            missing.append(AllowlistReason.TOO_FEW_FAILURE_GROUPS)
        if not missing:
            included = {s.target_id for s in good + bad}
            for target_id, items in by_target.items():
                if target_id in included:
                    evidence.extend(item.id for item in items)
        family = AllowlistFamilyResult(
            AddressFamily.IPV4,
            success_hosts,
            len(good_groups),
            failed_hosts,
            len(bad_groups),
            final_sites,
            tuple(missing),
        )
    verdict = _verdict(reasons, family, policy)

    def done(target_id: str) -> bool:
        items = [o for o in http if o.target_id == target_id]
        return not needs_tie_break(items) and any(
            o.attempt >= policy.confirmations
            or (o.status is ProbeStatus.SKIPPED and o.attempt == 1)
            for o in items
        )

    return AllowlistAssessment(
        verdict,
        (family,) if family is not None else (),
        tuple(reasons),
        tuple(dict.fromkeys(evidence)) if verdict is AllowlistVerdict.POSSIBLE else (),
        policy,
        checked_sites=sum(done(t.id) for t in targets),
        total_sites=len(targets),
        dns_unavailable=all_dns_unavailable,
    )


def _is_shared(site, groups, good_groups) -> bool:
    return site.state is AllowlistSiteState.UNAVAILABLE and groups[site.target_id] in good_groups


def _shared(site: AllowlistSiteResult) -> AllowlistSiteResult:
    return AllowlistSiteResult(
        site.target_id, site.hostname, AllowlistSiteState.SHARED_GROUP, site.russian_reference
    )


def _verdict(reasons, family, policy) -> AllowlistVerdict:
    if reasons:
        return AllowlistVerdict.INSUFFICIENT
    sites = family.sites if family else ()
    russian = [s for s in sites if s.russian_reference]
    common = [s for s in sites if not s.russian_reference]
    available = [s for s in sites if s.state is AllowlistSiteState.AVAILABLE]
    unavailable = [
        s
        for s in sites
        if s.state in (AllowlistSiteState.UNAVAILABLE, AllowlistSiteState.SHARED_GROUP)
    ]
    complete = bool(sites) and len(available) + len(unavailable) == len(sites)
    if (
        russian
        and common
        and any(s.state is AllowlistSiteState.AVAILABLE for s in russian)
        and all(s.state is AllowlistSiteState.UNAVAILABLE for s in common)
        and family is not None
        and not family.reasons
    ):
        return AllowlistVerdict.POSSIBLE
    if (
        complete
        and len(available) == len(sites)
        and family is not None
        and family.success_hosts >= policy.success_targets
        and family.success_groups >= policy.success_groups
    ):
        return AllowlistVerdict.NO_PATTERN
    if complete and len(unavailable) == len(sites):
        return AllowlistVerdict.NO_ACCESS
    if complete and available and unavailable:
        return AllowlistVerdict.PARTIAL_RESTRICTIONS
    return AllowlistVerdict.INSUFFICIENT
