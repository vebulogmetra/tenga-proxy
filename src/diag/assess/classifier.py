"""Выводы об одном запуске: порт DiagnosticClassifier.kt.

OBSERVED описывает измеренный факт, а не подтверждённую цензуру.
"""

from __future__ import annotations

from src.diag.assess import recommendations as rec
from src.diag.assess.allowlist import ClassificationContext, assess_allowlist, is_network_failure
from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticTermination,
    EvidenceLevel,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)

_PUBLIC_DNS = ("google-dns", "cloudflare-dns")


def _function_key(item) -> tuple[str, str, str]:
    return (item.target_id, item.evidence.get("transport", ""), item.evidence.get("coverage", ""))


def _group(items, key) -> dict:
    groups: dict = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def classify(
    report: DiagnosticReport, catalog: DiagnosticCatalog, context: ClassificationContext
) -> tuple[DiagnosticFinding, ...]:
    observations = report.observations
    findings: list[DiagnosticFinding] = []

    def add(code, level, evidence, *recommendations) -> None:
        ids = tuple(sorted({o.id for o in evidence}))
        findings.append(DiagnosticFinding(code, level, ids, tuple(recommendations)))

    stale = (
        catalog.expires_at <= context.now_epoch_seconds
        or report.context.catalog_version != str(catalog.catalog_version)
    )
    stable = (
        context.direct_context_stable
        and report.termination is not DiagnosticTermination.NETWORK_CHANGED
        and not any(o.failure_code is DiagnosticFailure.NETWORK_CHANGED for o in observations)
    )
    changed_session = any(
        o.failure_code is DiagnosticFailure.VPN_SESSION_CHANGED for o in observations
    )
    targets = {t.id: t for t in catalog.targets}
    direct = [o for o in observations if o.route is ProbeRoute.DIRECT]
    http = [o for o in direct if o.stage is ProbeStage.HTTP and o.target_id in targets]

    def of_purpose(item, *purposes) -> bool:
        target = targets.get(item.target_id)
        return target is not None and target.purpose in purposes

    if stale:
        add("CATALOG_STALE", EvidenceLevel.INSUFFICIENT_EVIDENCE, observations)
    portal = [o for o in observations if o.evidence.get("captivePortal") == "true"]
    if portal:
        add("CAPTIVE_PORTAL_REPORTED", EvidenceLevel.OBSERVED, portal)
    restricted = [o for o in observations if o.failure_code is DiagnosticFailure.SYSTEM_RESTRICTED]
    if restricted:
        add("SYSTEM_RESTRICTION", EvidenceLevel.OBSERVED, restricted, rec.CHECK_SYSTEM_NETWORK)
    auth = [o for o in observations if o.failure_code is DiagnosticFailure.PROXY_AUTH]
    if auth:
        add("PROXY_AUTH_FAILED", EvidenceLevel.OBSERVED, auth, rec.REPEAT_STABLE_NETWORK)
    session = [o for o in observations if o.failure_code is DiagnosticFailure.VPN_SESSION_CHANGED]
    if session:
        add("VPN_SESSION_CHANGED", EvidenceLevel.OBSERVED, session, rec.REPEAT_STABLE_NETWORK)
    rejected = [
        o for o in observations if o.stage is ProbeStage.HTTP and o.http_status in (403, 429)
    ]
    for group in _group(rejected, lambda o: (o.target_id, o.route)).values():
        add("HTTP_ACCESS_REJECTED", EvidenceLevel.OBSERVED, group, rec.RETRY_LATER)
    challenges = [
        o
        for o in observations
        if o.stage is ProbeStage.HTTP and o.evidence.get("coverage") == "web-challenge"
    ]
    if challenges:
        add(
            "POSSIBLE_WEB_CHALLENGE",
            EvidenceLevel.INSUFFICIENT_EVIDENCE,
            challenges,
            rec.RETRY_LATER,
        )
    system_failures = [
        o
        for o in direct
        if o.stage is ProbeStage.DNS
        and o.evidence.get("resolver") == "system"
        and o.status is ProbeStatus.FAILURE
        and o.failure_code in (DiagnosticFailure.DNS_FAILED, DiagnosticFailure.TIMEOUT)
    ]
    if system_failures:
        add("SYSTEM_DNS_FAILED", EvidenceLevel.OBSERVED, system_failures, rec.CHECK_SYSTEM_DNS)
    if stable:
        _udp_path(direct, add)
    controls = [
        o
        for o in direct
        if of_purpose(o, DiagnosticPurpose.CONTROL) and o.status is ProbeStatus.FAILURE
    ]
    if controls:
        add("CONTROL_LIMITED", EvidenceLevel.INSUFFICIENT_EVIDENCE, controls)
    # Любой прямой HTTP-ответ несовместим с заявлением о полном отказе сети.
    baseline_failures = [
        o
        for o in http
        if of_purpose(o, DiagnosticPurpose.BASELINE, DiagnosticPurpose.CONTROL)
        and is_network_failure(o)
    ]
    if baseline_failures and not any(
        o.status is ProbeStatus.SUCCESS or o.http_status is not None for o in http
    ):
        add(
            "NETWORK_UNVERIFIED",
            EvidenceLevel.INSUFFICIENT_EVIDENCE,
            baseline_failures,
            rec.CHECK_SYSTEM_NETWORK,
        )
    if stable:
        _tls_stage(direct, add)
        _ipv6(http, add)
    if stable and not stale:
        _dns_path(direct, http, system_failures, add)
    if stable and context.tunnel_comparison_valid and not changed_session:
        tunneled = [
            o
            for o in observations
            if o.route is ProbeRoute.ACTIVE_TUNNEL
            and o.stage is ProbeStage.HTTP
            and o.status is ProbeStatus.SUCCESS
            and o.evidence.get("responseMatched") == "true"
        ]
        for key, group in _group(tunneled, _function_key).items():
            same = [o for o in http if _function_key(o) == key]
            failed = [o for o in same if is_network_failure(o)]
            if failed and not any(o.status is ProbeStatus.SUCCESS for o in same):
                add(
                    "VPN_PATH_AVAILABLE",
                    EvidenceLevel.OBSERVED,
                    failed + group,
                    rec.USE_ACTIVE_VPN,
                )
    # Отказ вспомогательных узлов не говорит об ограничении посторонних ресурсов.
    candidates = [o for o in http if of_purpose(o, DiagnosticPurpose.BASELINE)]
    if any(o.status is ProbeStatus.SUCCESS for o in candidates) and any(
        is_network_failure(o) for o in candidates
    ):
        assessment = assess_allowlist(report, catalog, context)
        confirmed = [o for o in candidates if o.id in set(assessment.evidence_ids)]
        if confirmed:
            add(
                "POSSIBLE_ALLOWLIST",
                EvidenceLevel.LIKELY,
                confirmed,
                rec.TRY_OTHER_PROFILE,
                rec.REPEAT_STABLE_NETWORK,
            )
        else:
            add("ALLOWLIST_INSUFFICIENT_EVIDENCE", EvidenceLevel.INSUFFICIENT_EVIDENCE, candidates)
    return tuple(sorted(findings, key=lambda f: (f.code, ",".join(f.observation_ids))))


def _udp_path(direct, add) -> None:
    udp_all = [
        o
        for o in direct
        if o.stage is ProbeStage.UDP
        and o.target_id in _PUBLIC_DNS
        and o.evidence.get("coverage") == "dns-udp"
    ]
    for (target_id, family), udp in _group(
        udp_all, lambda o: (o.target_id, o.address_family)
    ).items():
        tcp = [
            o
            for o in direct
            if o.target_id == target_id
            and o.address_family is family
            and o.stage is ProbeStage.TCP
            and o.evidence.get("coverage") == "dns-tcp"
            and o.status is ProbeStatus.SUCCESS
            and o.evidence.get("responseMatched") == "true"
        ]
        if (
            all(is_network_failure(o) for o in udp)
            and len({o.attempt for o in udp}) >= 2
            and len({o.attempt for o in tcp}) >= 2
        ):
            add("DNS_UDP_PATH_FAILED", EvidenceLevel.OBSERVED, udp + tcp, rec.REPEAT_STABLE_NETWORK)


def _tls_stage(direct, add) -> None:
    failed = [
        o
        for o in direct
        if o.stage is ProbeStage.TLS
        and o.status is ProbeStatus.FAILURE
        and (is_network_failure(o) or o.failure_code is DiagnosticFailure.TLS_CERTIFICATE)
    ]
    for (target_id, family), group in _group(
        failed, lambda o: (o.target_id, o.address_family)
    ).items():
        tcp = [
            o
            for o in direct
            if o.target_id == target_id
            and o.address_family is family
            and o.stage is ProbeStage.TCP
            and o.status is ProbeStatus.SUCCESS
        ]
        if len({o.attempt for o in group}) >= 2 and tcp:
            add("TLS_STAGE_FAILURE", EvidenceLevel.OBSERVED, tcp + group)


def _ipv6(http, add) -> None:
    failed = [o for o in http if o.address_family is AddressFamily.IPV6 and is_network_failure(o)]
    for key, group in _group(failed, _function_key).items():
        v4 = [
            o
            for o in http
            if o.address_family is AddressFamily.IPV4
            and o.status is ProbeStatus.SUCCESS
            and _function_key(o) == key
        ]
        if v4 and len({o.attempt for o in group}) >= 2:
            add("IPV6_TESTS_FAILED", EvidenceLevel.OBSERVED, v4 + group, rec.REPEAT_STABLE_NETWORK)


def _dns_path(direct, http, system_failures, add) -> None:
    grouped = _group(system_failures, lambda o: (o.target_id, o.address_family))
    for (target_id, family), system in grouped.items():
        doh = [
            o
            for o in direct
            if o.target_id == target_id
            and o.address_family is family
            and o.stage is ProbeStage.DNS
            and o.status is ProbeStatus.SUCCESS
            and o.evidence.get("coverage") == "independent-bootstrap"
            and o.evidence.get("resolver") not in (None, "system")
            and o.evidence.get("dnsRcode") == "0"
        ]
        resolvers = {o.evidence.get("resolver") for o in doh}
        alternatives = [
            o
            for o in http
            if o.target_id == target_id
            and o.address_family is family
            and o.status is ProbeStatus.SUCCESS
            and o.evidence.get("responseMatched") == "true"
            and o.evidence.get("resolver") in resolvers
        ]
        if alternatives:
            used = {o.evidence.get("resolver") for o in alternatives}
            used_doh = [o for o in doh if o.evidence.get("resolver") in used]
            add(
                "DNS_PATH_PROBLEM",
                EvidenceLevel.LIKELY,
                system + used_doh + alternatives,
                rec.CHECK_SYSTEM_DNS,
            )
