"""Оценка DNS: порт DiagnosticDnsAssessor.kt.

Вывод делается по IPv4: отсутствие AAAA не говорит об отказе. Разные публичные ответы сами по
себе не подмена: подмена — это общая заглушка у разных владельцев или непубличный адрес.
"""

from __future__ import annotations

from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    DnsAssessment,
    DnsCheck,
    DnsCheckStatus,
    DnsVerdict,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
    PublicDnsFact,
    SecureDnsFact,
    SystemDnsFact,
)

_DOH = ("cloudflare-doh", "google-doh")
_RESOLVERS = ("system", *_DOH)
_PUBLIC = ("cloudflare-dns", "google-dns")
_UNANSWERED = frozenset(
    {
        DiagnosticFailure.TIMEOUT,
        DiagnosticFailure.CONNECTION_REFUSED,
        DiagnosticFailure.CONNECTION_RESET,
        DiagnosticFailure.IO,
    }
)
_PUBLIC_LABEL = {"cloudflare-dns": "Cloudflare", "google-dns": "Google"}


def _families(target) -> list[AddressFamily]:
    return [
        f
        for f in target.families
        if target.purpose is not DiagnosticPurpose.BASELINE or f is AddressFamily.IPV4
    ]


def _planned(scope) -> set[str]:
    planned: set[str] = set()
    for target in scope:
        families = _families(target)
        for family in families:
            planned.update(f"{target.id}-{family.name.lower()}-dns-{r}" for r in _RESOLVERS)
        if AddressFamily.IPV4 in families:
            planned.add(f"{target.id}-ipv4-dns-system-2")
            planned.add(f"{target.id}-ipv4-dns-consistency")
    for resolver in _PUBLIC:
        for protocol in ("udp", "tcp"):
            planned.update(f"{resolver}-{protocol}-{a}" for a in (1, 2))
    planned.update({"cloudflare-dns-identity", "google-dns-nxdomain"})
    return planned


def _check(group, label, resolver, family, network_changed) -> DnsCheck:
    good = any(o.status is ProbeStatus.SUCCESS for o in group)
    bad = any(o.status is not ProbeStatus.SUCCESS for o in group)
    repeated = all(
        any(o.attempt == attempt and o.status is ProbeStatus.FAILURE for o in group)
        for attempt in (1, 2)
    )
    problem = next((o for o in group if o.status is not ProbeStatus.SUCCESS), None)
    if network_changed:
        state = DnsCheckStatus.UNKNOWN
    elif not group:
        state = DnsCheckStatus.NOT_CHECKED
    elif any(o.evidence.get("responseMatched") == "false" for o in group):
        state = DnsCheckStatus.SUSPICIOUS
    elif good and bad:
        state = DnsCheckStatus.PARTIAL
    elif good:
        state = DnsCheckStatus.AVAILABLE
    elif any(o.failure_code is DiagnosticFailure.UNSAFE_ADDRESS for o in group):
        state = DnsCheckStatus.SUSPICIOUS
    elif repeated:
        state = DnsCheckStatus.UNAVAILABLE
    else:
        state = DnsCheckStatus.UNKNOWN
    failure = DiagnosticFailure.NETWORK_CHANGED if network_changed else None
    if failure is None and problem is not None:
        failure = problem.failure_code
    rcode = problem.evidence.get("dnsRcode") if problem else None
    return DnsCheck(label, resolver, state, failure, rcode, family)


def assess_dns(
    catalog: DiagnosticCatalog,
    observations,
    *,
    started: bool,
    completed: bool,
    network_changed: bool = False,
) -> DnsAssessment:
    scope = catalog.dns_targets()
    planned = _planned(scope)
    unique = {}
    for item in observations:
        if item.route is ProbeRoute.DIRECT and item.id in planned:
            unique.setdefault(item.id, item)
    items = list(unique.values())
    dns = [o for o in items if o.stage is ProbeStage.DNS]
    checks: list[DnsCheck] = []
    for target in scope:
        for family in _families(target):
            for resolver in _RESOLVERS:
                group = [
                    o
                    for o in dns
                    if o.target_id == target.id
                    and o.address_family is family
                    and o.evidence.get("resolver") == resolver
                ]
                checks.append(_check(group, target.hostname, resolver, family, network_changed))
    for resolver in _PUBLIC:
        for protocol in ("udp", "tcp"):
            group = [
                o
                for o in items
                if o.target_id == resolver
                and o.evidence.get("coverage", "").startswith(f"dns-{protocol}")
            ]
            label = f"{_PUBLIC_LABEL[resolver]} · {protocol.upper()}"
            checks.append(_check(group, label, protocol, None, network_changed))
    identity = [o for o in items if o.id == "cloudflare-dns-identity"]
    checks.append(_check(identity, "Cloudflare · id.server", "identity", None, network_changed))
    nxdomain = [o for o in items if o.id == "google-dns-nxdomain"]
    checks.append(_check(nxdomain, "Google · NXDOMAIN", "nxdomain", None, network_changed))

    targets = [t for t in scope if AddressFamily.IPV4 in t.families]
    spoofed: list[str] = []
    hidden: list[str] = []
    healthy = silent = 0
    doh_everywhere = bool(targets)
    for target in targets:
        target_dns = [
            o for o in dns if o.target_id == target.id and o.address_family is AddressFamily.IPV4
        ]
        system = [o for o in target_dns if o.evidence.get("resolver") == "system"]
        doh_both = all(
            any(
                o.evidence.get("resolver") == resolver and o.status is ProbeStatus.SUCCESS
                for o in target_dns
            )
            for resolver in _DOH
        )
        if not any(
            o.evidence.get("resolver") in _DOH and o.status is ProbeStatus.SUCCESS
            for o in target_dns
        ):
            doh_everywhere = False

        def repeated(match, attempts=system) -> bool:
            return all(any(o.attempt == a and match(o) for o in attempts) for a in (1, 2))

        consistency = next(
            (o for o in target_dns if o.evidence.get("coverage") == "answer-consistency"), None
        )
        stub = (
            consistency is not None
            and consistency.evidence.get("sharedAnswer") == "true"
            and consistency.evidence.get("dohOverlap") == "none"
        )
        if doh_both and (
            stub or any(o.failure_code is DiagnosticFailure.UNSAFE_ADDRESS for o in system)
        ):
            spoofed.append(target.hostname)
        elif doh_both and repeated(
            # SERVFAIL — отказ резолвера, а не заявление, что домена нет.
            lambda o: o.failure_code is DiagnosticFailure.DNS_FAILED
            and o.evidence.get("dnsRcode") != "2"
        ):
            hidden.append(target.hostname)
        elif repeated(lambda o: o.status is ProbeStatus.FAILURE and o.failure_code in _UNANSWERED):
            silent += 1
        elif len(system) >= 2 and all(o.status is ProbeStatus.SUCCESS for o in system):
            healthy += 1

    if spoofed:
        system_dns = SystemDnsFact.SPOOFS
    elif hidden:
        system_dns = SystemDnsFact.HIDES_DOMAINS
    elif targets and silent == len(targets) and doh_everywhere:
        system_dns = SystemDnsFact.NOT_RESPONDING
    elif silent > 0 and healthy > 0:
        system_dns = SystemDnsFact.UNSTABLE
    elif targets and healthy == len(targets):
        system_dns = SystemDnsFact.ANSWERS
    else:
        system_dns = SystemDnsFact.UNKNOWN

    public_items = [o for o in items if o.target_id in _PUBLIC]
    interception = [
        o for o in public_items if o.evidence.get("coverage") in ("dns-identity", "dns-nxdomain")
    ]
    transport = [o for o in public_items if o not in interception]
    if any(o.evidence.get("responseMatched") == "false" for o in interception):
        public_dns = PublicDnsFact.INTERCEPTED
    elif any(o.status is ProbeStatus.SUCCESS for o in transport):
        public_dns = PublicDnsFact.REACHES
    elif len(transport) == 8 and all(
        o.status is ProbeStatus.FAILURE and o.failure_code in _UNANSWERED for o in transport
    ):
        public_dns = PublicDnsFact.BLOCKED
    else:
        public_dns = PublicDnsFact.UNKNOWN

    target_ids = {t.id for t in targets}
    doh_checks = [
        o for o in dns if o.evidence.get("resolver") in _DOH and o.target_id in target_ids
    ]
    if doh_everywhere:
        secure_dns = SecureDnsFact.AVAILABLE
    elif (
        not any(o.status is ProbeStatus.SUCCESS for o in doh_checks)
        and any(o.status is ProbeStatus.FAILURE for o in doh_checks)
        and (healthy > 0 or public_dns is PublicDnsFact.REACHES)
    ):
        secure_dns = SecureDnsFact.BLOCKED
    else:
        secure_dns = SecureDnsFact.UNKNOWN

    unreliable = network_changed or not completed or not targets
    verdict = _verdict(unreliable, system_dns, public_dns, secure_dns)
    if unreliable:
        affected: list[str] = []
    elif system_dns is SystemDnsFact.SPOOFS:
        affected = spoofed
    elif system_dns is SystemDnsFact.HIDES_DOMAINS:
        affected = hidden
    else:
        affected = []
    return DnsAssessment(
        verdict,
        started,
        completed,
        len(items),
        len(planned),
        tuple(checks),
        doh_available=not network_changed
        and any(
            o.evidence.get("resolver") in _DOH and o.status is ProbeStatus.SUCCESS for o in dns
        ),
        system_dns=SystemDnsFact.UNKNOWN if unreliable else system_dns,
        public_dns=PublicDnsFact.UNKNOWN if unreliable else public_dns,
        secure_dns=SecureDnsFact.UNKNOWN if unreliable else secure_dns,
        affected_hosts=tuple(dict.fromkeys(affected)),
    )


def _verdict(unreliable, system_dns, public_dns, secure_dns) -> DnsVerdict:
    if unreliable:
        return DnsVerdict.UNKNOWN
    if system_dns is SystemDnsFact.SPOOFS:
        return DnsVerdict.SPOOFING
    if public_dns is PublicDnsFact.INTERCEPTED:
        return DnsVerdict.INTERCEPTION
    if system_dns is SystemDnsFact.HIDES_DOMAINS:
        return DnsVerdict.DOMAINS_HIDDEN
    if system_dns is SystemDnsFact.NOT_RESPONDING:
        return DnsVerdict.SYSTEM_NOT_RESPONDING
    if system_dns is SystemDnsFact.UNSTABLE:
        return DnsVerdict.UNSTABLE
    if system_dns is SystemDnsFact.ANSWERS and secure_dns is SecureDnsFact.BLOCKED:
        return DnsVerdict.WORKING_DOH_BLOCKED
    if system_dns is SystemDnsFact.ANSWERS:
        return DnsVerdict.WORKING
    return DnsVerdict.UNKNOWN
