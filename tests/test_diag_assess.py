"""Сценарии из тестов Android: оценка должна давать те же выводы на тех же наблюдениях."""

import pytest

from src.diag.assess import recommendations as rec
from src.diag.assess.allowlist import ClassificationContext
from src.diag.assess.causes import assess_causes
from src.diag.assess.classifier import classify
from src.diag.assess.dns import assess_dns
from src.diag.assess.services import assess_services
from src.diag.assess.summary import SummaryVerdict, summarize
from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose, DiagnosticTarget
from src.diag.models import (
    AddressFamily,
    AllowlistAssessment,
    AllowlistPolicy,
    AllowlistVerdict,
    CauseAssessment,
    DiagnosticFailure,
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticTermination,
    DnsAssessment,
    DnsCheckStatus,
    DnsVerdict,
    EvidenceLevel,
    FailureCause,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
    PublicDnsFact,
    SecureDnsFact,
    ServiceAssessment,
    ServiceCheck,
    ServiceCheckStatus,
    ServiceRoute,
    SystemDnsFact,
)
from src.diag.plan import with_changes

V4 = (AddressFamily.IPV4,)
F = DiagnosticFailure
S = ProbeStatus

# Сервисы

TG = DiagnosticTarget(
    "telegram-web",
    "web.telegram.org",
    "telegram",
    purpose=DiagnosticPurpose.TELEGRAM_WEB,
    families=V4,
)
SERVICE_CATALOG = DiagnosticCatalog(1, 5, 999_999, (TG,))


def service_item(attempt, status, failure=None, http=None, route=ProbeRoute.DIRECT):
    item_id = (
        f"telegram-web-ipv4-http-{attempt}" if route is ProbeRoute.DIRECT else "telegram-web-tunnel"
    )
    return ProbeObservation(
        item_id, TG.id, route, ProbeStage.HTTP, status, attempt=attempt,
        address_family=AddressFamily.IPV4, failure_code=failure, http_status=http,
    )  # fmt: skip


def assess_service(*items, changed=False, tunnel_changed=False):
    return assess_services(
        SERVICE_CATALOG, items, started=True, completed=True, compare_tunnel=True,
        network_changed=changed, tunnel_changed=tunnel_changed,
    )  # fmt: skip


def service_status(*items):
    return assess_service(*items).routes[0].checks[0].status


def test_one_timeout_is_unknown_two_confirm_unavailability():
    first = service_item(1, S.FAILURE, F.TIMEOUT)
    assert service_status(first) is ServiceCheckStatus.UNKNOWN
    second = service_item(2, S.FAILURE, F.TIMEOUT)
    assert service_status(first, second) is ServiceCheckStatus.UNAVAILABLE


def test_server_rejection_is_not_a_network_outage():
    items = [service_item(a, S.FAILURE, F.HTTP_REJECTED, 403) for a in (1, 2)]
    assert service_status(*items) is ServiceCheckStatus.UNKNOWN


def test_mixed_waves_are_partial_and_network_change_invalidates_success():
    first = service_item(1, S.SUCCESS)
    second = service_item(2, S.FAILURE, F.CONNECTION_RESET)
    assert service_status(first, second) is ServiceCheckStatus.PARTIAL
    changed = assess_service(first, changed=True)
    assert changed.routes[0].checks[0].status is ServiceCheckStatus.UNKNOWN


def test_unstarted_checks_and_planned_denominator():
    result = assess_services(
        SERVICE_CATALOG, [], started=False, completed=False, compare_tunnel=True
    )
    assert (result.total, result.checked) == (3, 0)
    assert result.routes[0].checks[0].status is ServiceCheckStatus.NOT_CHECKED


def test_progress_counts_cancellations_without_family():
    cancelled = with_changes(service_item(1, S.CANCELLED, F.DEADLINE), address_family=None)
    assert assess_service(cancelled).checked == 1


def test_vpn_results_do_not_change_direct_verdict():
    result = assess_service(
        service_item(1, S.FAILURE, F.TIMEOUT),
        service_item(2, S.FAILURE, F.TIMEOUT),
        service_item(1, S.SUCCESS, route=ProbeRoute.ACTIVE_TUNNEL),
    )
    assert result.routes[0].checks[0].status is ServiceCheckStatus.UNAVAILABLE
    assert result.routes[1].checks[0].status is ServiceCheckStatus.AVAILABLE


def test_vpn_change_invalidates_only_the_comparison():
    result = assess_service(
        service_item(1, S.SUCCESS),
        service_item(1, S.SUCCESS, route=ProbeRoute.ACTIVE_TUNNEL),
        tunnel_changed=True,
    )
    assert result.routes[0].checks[0].status is ServiceCheckStatus.AVAILABLE
    assert result.routes[1].checks[0].status is ServiceCheckStatus.UNKNOWN
    assert result.routes[1].checks[0].failure is F.VPN_SESSION_CHANGED


def test_unsafe_dns_explains_skipped_function():
    dns = [
        ProbeObservation(
            f"dns-{resolver}", TG.id, ProbeRoute.DIRECT, ProbeStage.DNS,
            S.INCONCLUSIVE if resolver == "system" else S.FAILURE,
            failure_code=F.UNSAFE_ADDRESS if resolver == "system" else F.CONNECTION_RESET,
            address_family=AddressFamily.IPV4, evidence={"resolver": resolver},
        )
        for resolver in ("system", "google-doh", "cloudflare-doh")
    ]  # fmt: skip
    skipped = [service_item(a, S.SKIPPED, F.DNS_FAILED) for a in (1, 2)]
    check = assess_service(*dns, *skipped).routes[0].checks[0]
    assert check.status is ServiceCheckStatus.UNKNOWN
    assert check.failure is F.UNSAFE_ADDRESS


# DNS

A_B = (
    DiagnosticTarget("a", "example.org", "one", families=V4),
    DiagnosticTarget("b", "example.com", "two", families=V4),
)
DNS_CATALOG = DiagnosticCatalog(1, 1, 100, A_B)


def query(target, resolver, status=S.SUCCESS, attempt=1, failure=None, rcode="0"):
    suffix = "-2" if attempt == 2 else ""
    return ProbeObservation(
        f"{target}-ipv4-dns-{resolver}{suffix}", target, ProbeRoute.DIRECT, ProbeStage.DNS, status,
        attempt=attempt, failure_code=failure, address_family=AddressFamily.IPV4,
        evidence={"resolver": resolver, "dnsRcode": rcode},
    )  # fmt: skip


def all_dns(failed=(), failure=F.TIMEOUT, rcode="unknown"):
    items = []
    for target in A_B:
        bad = target.id in failed
        status = S.FAILURE if bad else S.SUCCESS
        code = failure if bad else None
        value = rcode if bad else "0"
        items += [
            query(target.id, "system", status, 1, code, value),
            query(target.id, "system", status, 2, code, value),
            query(target.id, "cloudflare-doh"),
            query(target.id, "google-doh"),
        ]
    return items


def assess_d(items, changed=False, catalog=DNS_CATALOG):
    return assess_dns(catalog, items, started=True, completed=True, network_changed=changed)


def consistency(target, overlap, shared):
    return ProbeObservation(
        f"{target}-ipv4-dns-consistency", target, ProbeRoute.DIRECT, ProbeStage.DNS, S.SUCCESS,
        address_family=AddressFamily.IPV4,
        evidence={
            "coverage": "answer-consistency", "dohOverlap": overlap,
            "sharedAnswer": str(shared).lower(),
        },
    )  # fmt: skip


def interception(item_id, target, matched):
    coverage = "dns-identity" if item_id.endswith("identity") else "dns-nxdomain"
    return ProbeObservation(
        item_id, target, ProbeRoute.DIRECT, ProbeStage.UDP,
        S.SUCCESS if matched else S.INCONCLUSIVE,
        evidence={"coverage": coverage, "responseMatched": str(matched).lower()},
    )  # fmt: skip


def doh_failed(items):
    return [
        with_changes(o, status=S.FAILURE, failure_code=F.CONNECTION_RESET)
        if o.evidence.get("resolver") != "system"
        else o
        for o in items
    ]


def test_healthy_system_survives_blocked_port_53():
    udp = ProbeObservation(
        "cloudflare-dns-udp-1", "cloudflare-dns", ProbeRoute.DIRECT, ProbeStage.UDP, S.FAILURE,
        failure_code=F.TIMEOUT, evidence={"coverage": "dns-udp"},
    )  # fmt: skip
    assert assess_d([*all_dns(), udp]).verdict is DnsVerdict.WORKING


def test_repeat_failures_identify_unavailable_dns():
    result = assess_d(all_dns({"a", "b"}))
    assert result.verdict is DnsVerdict.SYSTEM_NOT_RESPONDING
    assert result.system_dns is SystemDnsFact.NOT_RESPONDING


def test_some_failures_are_unstable():
    assert assess_d(all_dns({"a"})).verdict is DnsVerdict.UNSTABLE


def test_nxdomain_needs_independent_answers():
    result = assess_d(all_dns({"a"}, F.DNS_FAILED, "3"))
    assert result.verdict is DnsVerdict.DOMAINS_HIDDEN
    assert result.affected_hosts == ("example.org",)
    system_only = [o for o in all_dns({"a", "b"}) if o.evidence["resolver"] == "system"]
    assert assess_d(system_only).verdict is DnsVerdict.UNKNOWN


def test_servfail_is_not_hidden_domains():
    assert assess_d(all_dns({"a"}, F.DNS_FAILED, "2")).verdict is not DnsVerdict.DOMAINS_HIDDEN


def test_unsafe_answer_needs_confirmation():
    items = [
        with_changes(o, status=S.INCONCLUSIVE, failure_code=F.UNSAFE_ADDRESS)
        if o.target_id == "a" and o.evidence["resolver"] == "system"
        else o
        for o in all_dns()
    ]
    assert assess_d(items).verdict is DnsVerdict.SPOOFING
    only = [o for o in items if o.evidence["resolver"] == "system"]
    assert assess_d(only).verdict is DnsVerdict.UNKNOWN


def test_missing_repeat_and_network_change_are_not_definitive():
    first = [o for o in all_dns({"a", "b"}) if o.attempt == 1]
    assert assess_d(first).verdict is DnsVerdict.UNKNOWN
    assert assess_d(all_dns(), changed=True).verdict is DnsVerdict.UNKNOWN


def test_ipv6_empty_answers_do_not_override_ipv4():
    ipv6 = with_changes(
        query("a", "system", S.FAILURE, failure=F.DNS_FAILED),
        id="a-ipv6-dns-system",
        address_family=AddressFamily.IPV6,
    )
    assert assess_d([*all_dns(), ipv6]).verdict is DnsVerdict.WORKING


def test_dns_progress_counts_planned_once():
    items = all_dns()
    result = assess_d([*items, with_changes(items[0], id="unplanned")])
    assert result.checked == 8
    assert result.total == 20
    assert assess_d([]).verdict is DnsVerdict.UNKNOWN


def test_partial_failures_useful_when_doh_resets():
    items = doh_failed(all_dns({"a"}))
    result = assess_d(items)
    assert result.verdict is DnsVerdict.UNSTABLE
    assert result.secure_dns is SecureDnsFact.BLOCKED
    assert not result.doh_available
    assert assess_d([o for o in items if o.attempt == 1]).verdict is DnsVerdict.UNKNOWN


def test_shared_stub_is_spoofing():
    result = assess_d([*all_dns(), consistency("a", "none", True), consistency("b", "none", True)])
    assert result.verdict is DnsVerdict.SPOOFING
    assert result.system_dns is SystemDnsFact.SPOOFS
    assert result.affected_hosts == ("example.org", "example.com")


def test_different_cdn_answers_are_not_spoofing():
    items = [*all_dns(), consistency("a", "none", False), consistency("b", "partial", False)]
    assert assess_d(items).verdict is DnsVerdict.WORKING


def test_foreign_answer_is_interception():
    bad = interception("cloudflare-dns-identity", "cloudflare-dns", False)
    result = assess_d([*all_dns(), bad])
    assert result.verdict is DnsVerdict.INTERCEPTION
    assert result.public_dns is PublicDnsFact.INTERCEPTED
    identity = next(c for c in result.checks if c.resolver == "identity")
    assert identity.status is DnsCheckStatus.SUSPICIOUS
    good = interception("cloudflare-dns-identity", "cloudflare-dns", True)
    assert assess_d([*all_dns(), good]).verdict is DnsVerdict.WORKING


def test_working_system_with_doh_blocked():
    result = assess_d(doh_failed(all_dns()))
    assert result.verdict is DnsVerdict.WORKING_DOH_BLOCKED
    assert result.secure_dns is SecureDnsFact.BLOCKED


def test_instagram_does_not_affect_dns_stage():
    instagram = DiagnosticTarget(
        "i", "www.instagram.com", "meta", purpose=DiagnosticPurpose.INSTAGRAM_WEB, families=V4
    )
    catalog = DiagnosticCatalog(1, 1, 100, (*A_B, instagram))
    items = [
        *all_dns(),
        query("i", "system", S.FAILURE, 1, F.DNS_FAILED, "3"),
        query("i", "system", S.FAILURE, 2, F.DNS_FAILED, "3"),
        query("i", "cloudflare-doh"),
        query("i", "google-doh"),
    ]
    result = assess_d(items, catalog=catalog)
    assert result.verdict is DnsVerdict.WORKING
    assert not any(c.label == "www.instagram.com" for c in result.checks)


# Причины


def probe(target, stage, attempt, status, failure=None):
    return ProbeObservation(
        f"{target}-{stage.name}-{attempt}", target, ProbeRoute.DIRECT, stage, status,
        attempt=attempt, failure_code=failure, address_family=AddressFamily.IPV4,
    )  # fmt: skip


def ok(target, stage):
    return [probe(target, stage, a, S.SUCCESS) for a in (1, 2)]


def failed(target, stage, failure=F.TIMEOUT):
    return [probe(target, stage, a, S.FAILURE, failure) for a in (1, 2)]


TCP = ProbeStage.TCP
TLS = ProbeStage.TLS


@pytest.mark.parametrize(
    ("items", "cause"),
    [
        (failed("a", TCP), FailureCause.CONNECTION_FAILED),
        (
            ok("a", TCP) + failed("a", TLS, F.CONNECTION_RESET) + ok("c", TCP) + ok("c", TLS),
            FailureCause.TLS_BLOCKED_BY_NAME,
        ),
        (
            ok("a", TCP)
            + failed("a", TLS, F.TLS_FAILED)
            + ok("c", TCP)
            + failed("c", TLS, F.TLS_FAILED),
            FailureCause.TLS_FAILED,
        ),
        (
            [*ok("a", TCP), probe("a", TLS, 1, S.FAILURE, F.TLS_CERTIFICATE)],
            FailureCause.CERTIFICATE,
        ),
        (ok("a", TCP) + ok("a", TLS), FailureCause.AFTER_HANDSHAKE),
    ],
)
def test_cause_of_failure(items, cause):
    assert assess_causes(items, {"a"}).causes["a"] is cause


def test_no_cause_without_evidence():
    partial = [
        *ok("a", TCP),
        probe("a", TLS, 1, S.SUCCESS),
        probe("a", TLS, 2, S.FAILURE, F.TLS_FAILED),
    ]
    assert "a" not in assess_causes(partial, {"a"}).causes
    skipped = [probe("a", TCP, a, S.SKIPPED, F.DNS_FAILED) for a in (1, 2)]
    assert "a" not in assess_causes(skipped, {"a"}).causes
    other_route = [with_changes(o, route=ProbeRoute.ACTIVE_TUNNEL) for o in failed("a", TCP)]
    v6 = [with_changes(o, address_family=AddressFamily.IPV6) for o in failed("a", TLS)]
    assert "a" not in assess_causes(other_route + v6, {"a"}).causes


def test_controls_are_not_counted_and_most_common_wins():
    items = (
        failed("a", TCP) + failed("b", TCP) + ok("c", TCP) + ok("c", TLS) + failed("control", TCP)
    )
    result = assess_causes(items, ["a", "b", "c"])
    assert "control" not in result.causes
    assert list(result.top_causes) == [FailureCause.CONNECTION_FAILED]
    assert result.top_cause_count == 2
    assert result.total == 3


def test_tie_names_every_leading_cause():
    result = CauseAssessment(
        {
            "a": FailureCause.TLS_FAILED,
            "b": FailureCause.CONNECTION_FAILED,
            "c": FailureCause.TLS_FAILED,
            "d": FailureCause.CONNECTION_FAILED,
            "e": FailureCause.CERTIFICATE,
        },
        6,
    )
    assert list(result.top_causes) == [FailureCause.CONNECTION_FAILED, FailureCause.TLS_FAILED]
    assert result.top_cause_count == 2
    assert not CauseAssessment().top_causes


# Выводы

TARGETS = (
    DiagnosticTarget("a", "first.example", "one"),
    DiagnosticTarget("b", "second.example", "two"),
)
CATALOG = DiagnosticCatalog(1, 1, 2_000_000_000, TARGETS)
CONTEXT = ClassificationContext(1_900_000_000, direct_context_stable=True)


def obs(item_id, target="a", stage=ProbeStage.HTTP, status=S.SUCCESS, failure=None,
        route=ProbeRoute.DIRECT, family=AddressFamily.IPV4, attempt=1, evidence=None, http=None):  # fmt: skip
    return ProbeObservation(
        item_id, target, route, stage, status, attempt=attempt, failure_code=failure,
        address_family=family, evidence=evidence or {}, http_status=http,
    )  # fmt: skip


def run_classify(
    items, context=CONTEXT, catalog=CATALOG, termination=DiagnosticTermination.COMPLETED
):
    report = DiagnosticReport(
        DiagnosticRunContext("run", "1", "test"), tuple(items), termination=termination
    )
    return classify(report, catalog, context)


def codes(items, **kw):
    return [f.code for f in run_classify(items, **kw)]


SYSTEM_FAIL = obs(
    "system", stage=ProbeStage.DNS, status=S.FAILURE, failure=F.DNS_FAILED,
    evidence={"resolver": "system"},
)  # fmt: skip
DOH_OK = obs(
    "doh", stage=ProbeStage.DNS,
    evidence={"resolver": "google-doh", "coverage": "independent-bootstrap", "dnsRcode": "0"},
)  # fmt: skip
ALTERNATIVE = obs("alternative", evidence={"resolver": "google-doh", "responseMatched": "true"})


def test_dns_path_needs_doh_and_verified_https():
    assert "DNS_PATH_PROBLEM" not in codes([SYSTEM_FAIL, DOH_OK])
    finding = next(
        f for f in run_classify([SYSTEM_FAIL, DOH_OK, ALTERNATIVE]) if f.code == "DNS_PATH_PROBLEM"
    )
    assert finding.level is EvidenceLevel.LIKELY
    assert set(finding.observation_ids) == {"system", "doh", "alternative"}
    assert rec.CHECK_SYSTEM_DNS in finding.recommendation_codes
    v6 = with_changes(ALTERNATIVE, address_family=AddressFamily.IPV6)
    assert "DNS_PATH_PROBLEM" not in codes([SYSTEM_FAIL, DOH_OK, v6])
    stale = ClassificationContext(2_100_000_000, direct_context_stable=True)
    assert "DNS_PATH_PROBLEM" not in codes([SYSTEM_FAIL, DOH_OK, ALTERNATIVE], context=stale)


def test_successful_answers_imply_nothing():
    items = [
        obs("system", stage=ProbeStage.DNS, evidence={"resolver": "system"}),
        obs(
            "doh", stage=ProbeStage.DNS,
            evidence={"resolver": "google-doh", "coverage": "independent-bootstrap"},
        ),
    ]  # fmt: skip
    assert run_classify(items) == ()


def test_vpn_comparison_needs_compatible_session():
    direct = obs("direct", status=S.FAILURE, failure=F.TIMEOUT)
    tunnel = obs(
        "tunnel", route=ProbeRoute.ACTIVE_TUNNEL, family=None, evidence={"responseMatched": "true"}
    )
    compatible = ClassificationContext(
        1_900_000_000, direct_context_stable=True, tunnel_comparison_valid=True
    )
    assert "VPN_PATH_AVAILABLE" not in codes([direct, tunnel])
    finding = next(
        f for f in run_classify([direct, tunnel], compatible) if f.code == "VPN_PATH_AVAILABLE"
    )
    assert finding.level is EvidenceLevel.OBSERVED
    assert set(finding.observation_ids) == {"direct", "tunnel"}
    other = obs("other-family", family=AddressFamily.IPV6)
    assert "VPN_PATH_AVAILABLE" not in codes([direct, tunnel, other], context=compatible)
    changed = obs(
        "changed", route=ProbeRoute.ACTIVE_TUNNEL, status=S.CANCELLED,
        failure=F.VPN_SESSION_CHANGED,
    )  # fmt: skip
    assert "VPN_PATH_AVAILABLE" not in codes([direct, tunnel, changed], context=compatible)
    assert "VPN_PATH_AVAILABLE" not in codes(
        [direct, tunnel], context=compatible, termination=DiagnosticTermination.NETWORK_CHANGED
    )
    net = obs("n", stage=ProbeStage.NETWORK, status=S.CANCELLED, failure=F.NETWORK_CHANGED)
    assert "VPN_PATH_AVAILABLE" not in codes([direct, tunnel, net], context=compatible)


def test_tls_stage_failure_names_no_filter():
    items = [
        obs("tcp", stage=TCP),
        obs("tls1", stage=TLS, status=S.FAILURE, failure=F.CONNECTION_RESET),
        obs("tls2", stage=TLS, status=S.FAILURE, failure=F.TLS_FAILED, attempt=2),
    ]
    findings = run_classify(items)
    finding = next(f for f in findings if f.code == "TLS_STAGE_FAILURE")
    assert finding.level is EvidenceLevel.OBSERVED
    assert finding.recommendation_codes == ()
    assert not any("DPI" in f.code or "SNI" in f.code for f in findings)


def test_ipv6_failure_requires_repetition():
    v6 = AddressFamily.IPV6
    items = [
        obs("v4"),
        obs("v6a", family=v6, status=S.FAILURE, failure=F.TIMEOUT),
        obs("v6b", family=v6, status=S.FAILURE, failure=F.TIMEOUT, attempt=2),
    ]
    assert "IPV6_TESTS_FAILED" in codes(items)
    assert "IPV6_TESTS_FAILED" not in codes(items[:-1])


GOOD = tuple(
    DiagnosticTarget(f"ok-{i}", ("yandex.ru", "ya.ru", "vk.com")[i], f"ok-group-{i % 2}")
    for i in range(3)
)
BAD = tuple(DiagnosticTarget(f"bad-{i}", f"bad{i}.example", f"bad-group-{i % 3}") for i in range(6))
ALL = GOOD + BAD
ALL_CATALOG = DiagnosticCatalog(1, 1, 2_000_000_000, ALL)
VERIFIED = ClassificationContext(
    1_900_000_000,
    direct_context_stable=True,
    verified_placement_groups=frozenset(t.placement_group for t in ALL),
)


def allowlist_items():
    return [
        obs(
            f"{t.id}-{attempt}", t.id, attempt=attempt,
            status=S.SUCCESS if t in GOOD else S.FAILURE,
            failure=None if t in GOOD else F.TIMEOUT,
            evidence={
                "responseMatched": str(t in GOOD).lower(),
                "placementGroup": t.placement_group,
            },
        )
        for t in ALL
        for attempt in (1, 2)
    ]  # fmt: skip


def possible(
    items, context=VERIFIED, catalog=ALL_CATALOG, termination=DiagnosticTermination.COMPLETED
):
    return "POSSIBLE_ALLOWLIST" in codes(
        items, context=context, catalog=catalog, termination=termination
    )


def test_allowlist_needs_verified_fresh_groups_and_two_waves():
    items = allowlist_items()
    assert possible(items)
    unverified = ClassificationContext(1_900_000_000, direct_context_stable=True)
    assert not possible(items, unverified)
    no_placement = [
        with_changes(o, evidence={"responseMatched": o.evidence["responseMatched"]}) for o in items
    ]
    assert not possible(no_placement)
    assert not possible([o for o in items if o.attempt == 1])
    stale = ClassificationContext(
        2_100_000_000,
        direct_context_stable=True,
        verified_placement_groups=VERIFIED.verified_placement_groups,
    )
    assert not possible(items, stale)
    assert not possible(items, termination=DiagnosticTermination.USER_CANCELLED)
    waf = [
        with_changes(o, http_status=403, failure_code=F.HTTP_REJECTED)
        if o.status is S.FAILURE
        else o
        for o in items
    ]
    assert not possible(waf)
    split = [
        with_changes(o, address_family=AddressFamily.IPV6) if o.status is S.FAILURE else o
        for o in items
    ]
    assert not possible(split)


def test_control_outage_does_not_imply_network_outage():
    control = DiagnosticTarget("a", "first.example", "one", purpose=DiagnosticPurpose.CONTROL)
    catalog = DiagnosticCatalog(1, 1, 2_000_000_000, (control, TARGETS[1]))
    items = [obs("helper", status=S.FAILURE, failure=F.TIMEOUT), obs("baseline", target="b")]
    found = codes(items, catalog=catalog)
    assert "CONTROL_LIMITED" in found
    assert "NETWORK_UNVERIFIED" not in found


def test_udp_dns_failure_needs_repeated_tcp_controls():
    udp = [
        obs(
            f"udp-{a}", "google-dns", ProbeStage.UDP, S.FAILURE, F.TIMEOUT, attempt=a,
            evidence={"coverage": "dns-udp", "transport": "udp"},
        )
        for a in (1, 2)
    ]  # fmt: skip
    tcp = [
        obs(
            f"tcp-{a}", "google-dns", TCP, attempt=a,
            evidence={"coverage": "dns-tcp", "transport": "tcp", "responseMatched": "true"},
        )
        for a in (1, 2)
    ]  # fmt: skip
    assert "DNS_UDP_PATH_FAILED" in codes(udp + tcp)
    assert "UDP_BLOCKED" not in codes(udp + tcp)
    assert "DNS_UDP_PATH_FAILED" not in codes(udp[:1] + tcp)
    v6 = [with_changes(o, address_family=AddressFamily.IPV6) for o in tcp]
    assert "DNS_UDP_PATH_FAILED" not in codes(udp + v6)


def test_system_restriction_has_a_finding():
    item = obs("x", status=S.SKIPPED, failure=F.SYSTEM_RESTRICTED)
    assert "SYSTEM_RESTRICTION" in codes([item])


# Общий вывод


def s_allowlist(verdict):
    return AllowlistAssessment(verdict, (), (), policy=AllowlistPolicy(), completed=True)


def s_services(telegram, instagram, youtube, completed=True):
    return ServiceAssessment(
        True, completed, 6, 6,
        (
            ServiceRoute(
                ProbeRoute.DIRECT,
                (
                    ServiceCheck("t", DiagnosticPurpose.TELEGRAM_WEB, telegram),
                    ServiceCheck("i", DiagnosticPurpose.INSTAGRAM_WEB, instagram),
                    ServiceCheck("y", DiagnosticPurpose.YOUTUBE_WEB, youtube),
                ),
            ),
        ),
    )  # fmt: skip


UP = ServiceCheckStatus.AVAILABLE
DOWN = ServiceCheckStatus.UNAVAILABLE
ALL_UP = s_services(UP, UP, UP)
ALL_DOWN = s_services(DOWN, DOWN, DOWN)


def summary(
    a=AllowlistVerdict.NO_PATTERN, s=ALL_UP, d=DnsVerdict.WORKING, networks=("WIFI",), partial=False
):
    dns = DnsAssessment(d, True, True, 1, 1, ())
    return summarize(s_allowlist(a), s, dns, networks, partial)


@pytest.mark.parametrize(
    ("kwargs", "verdict"),
    [
        (
            {"a": AllowlistVerdict.NO_ACCESS, "networks": ("WIFI", "ETHERNET")},
            SummaryVerdict.MIXED_NETWORKS,
        ),
        ({"networks": ("WIFI", None)}, SummaryVerdict.ALL_AVAILABLE),
        ({"a": AllowlistVerdict.NO_ACCESS}, SummaryVerdict.NO_ACCESS),
        ({"a": AllowlistVerdict.POSSIBLE, "s": ALL_DOWN}, SummaryVerdict.ALLOWLIST),
        ({"a": AllowlistVerdict.PARTIAL_RESTRICTIONS}, SummaryVerdict.PARTIAL_RESOURCES),
        ({"s": ALL_DOWN}, SummaryVerdict.SERVICES_BLOCKED),
        ({"a": AllowlistVerdict.INSUFFICIENT, "s": ALL_DOWN}, SummaryVerdict.SERVICES_BLOCKED),
        ({"s": s_services(DOWN, DOWN, DOWN, completed=False)}, SummaryVerdict.UNKNOWN),
        ({"d": DnsVerdict.WORKING_DOH_BLOCKED}, SummaryVerdict.ALL_AVAILABLE),
        ({"d": DnsVerdict.UNSTABLE}, SummaryVerdict.UNKNOWN),
        ({"s": s_services(UP, ServiceCheckStatus.PARTIAL, UP)}, SummaryVerdict.UNKNOWN),
        ({"a": AllowlistVerdict.INSUFFICIENT}, SummaryVerdict.UNKNOWN),
    ],
)
def test_summary_verdict(kwargs, verdict):
    assert summary(**kwargs).verdict is verdict


def test_some_services_blocked_names_them():
    result = summary(s=s_services(UP, DOWN, UP))
    assert result.verdict is SummaryVerdict.SOME_SERVICES_BLOCKED
    assert result.blocked_services == ("Instagram",)


@pytest.mark.parametrize(
    "verdict",
    [
        DnsVerdict.SPOOFING,
        DnsVerdict.INTERCEPTION,
        DnsVerdict.DOMAINS_HIDDEN,
        DnsVerdict.SYSTEM_NOT_RESPONDING,
    ],
)
def test_dns_problems_follow_services(verdict):
    result = summary(d=verdict)
    assert result.verdict is SummaryVerdict.DNS_PROBLEM
    assert result.dns_verdict is verdict


def test_partial_flag_is_carried():
    assert summary(partial=True).incomplete
