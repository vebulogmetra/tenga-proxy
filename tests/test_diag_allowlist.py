import pytest

from src.diag.assess.allowlist import ClassificationContext, assess_allowlist, needs_tie_break
from src.diag.catalog import DiagnosticCatalog, DiagnosticTarget
from src.diag.models import (
    AddressFamily,
    AllowlistReason,
    AllowlistSiteState,
    AllowlistVerdict,
    DiagnosticFailure,
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticTermination,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.plan import with_changes

HOSTS = ("yandex.ru", "ya.ru", "vk.com")
TARGETS = tuple(
    DiagnosticTarget(
        f"t{i}",
        HOSTS[i] if i < 3 else f"site{i}.example",
        f"good-{i % 2}" if i < 3 else f"bad-{i % 3}",
    )
    for i in range(9)
)
CATALOG = DiagnosticCatalog(1, 1, 999_999, TARGETS)
CONTEXT = ClassificationContext(
    100,
    direct_context_stable=True,
    verified_placement_groups=frozenset(t.placement_group for t in TARGETS),
)


def items():
    return [
        ProbeObservation(
            f"{t.id}-{attempt}", t.id, ProbeRoute.DIRECT, ProbeStage.HTTP,
            ProbeStatus.SUCCESS if index < 3 else ProbeStatus.FAILURE,
            attempt=attempt,
            failure_code=None if index < 3 else DiagnosticFailure.TIMEOUT,
            address_family=AddressFamily.IPV4,
            evidence={"placementGroup": t.placement_group, "responseMatched": "true"},
        )
        for index, t in enumerate(TARGETS)
        for attempt in (1, 2)
    ]  # fmt: skip


def report(observations, termination=DiagnosticTermination.COMPLETED):
    return DiagnosticReport(
        DiagnosticRunContext("r", "1", "1.4.5"), tuple(observations), termination=termination
    )


def assess(observations=None, termination=DiagnosticTermination.COMPLETED, context=CONTEXT):
    observations = items() if observations is None else observations
    return assess_allowlist(report(observations, termination), CATALOG, context)


def ok(item):
    return with_changes(item, status=ProbeStatus.SUCCESS, failure_code=None)


def failed(item, code=DiagnosticFailure.TIMEOUT):
    return with_changes(item, status=ProbeStatus.FAILURE, failure_code=code)


def site(result, target_id):
    return next(s for s in result.families[0].sites if s.target_id == target_id)


def test_positive_assessment_counts_distinct_hosts_and_groups():
    result = assess()
    assert result.verdict is AllowlistVerdict.POSSIBLE
    family = result.families[0]
    assert family.success_hosts == 3
    assert family.success_groups == 2
    assert family.failed_hosts == 6
    assert family.failed_groups == 3
    assert len(result.evidence_ids) == 18
    assert family.reasons == ()


def test_missing_confirmation_explains_exclusion():
    result = assess([o for o in items() if not (o.target_id == "t8" and o.attempt == 2)])
    assert result.verdict is AllowlistVerdict.INSUFFICIENT
    assert result.families[0].failed_hosts == 5
    assert site(result, "t8").state is AllowlistSiteState.MISSING_REPEAT
    assert AllowlistReason.TOO_FEW_FAILURES in result.families[0].reasons


def test_untrusted_placement_and_rejection_differ():
    def change(item):
        if item.target_id == "t7":
            return with_changes(item, evidence={})
        if item.target_id == "t8":
            return with_changes(
                item,
                status=ProbeStatus.INCONCLUSIVE,
                http_status=403,
                failure_code=DiagnosticFailure.HTTP_REJECTED,
            )
        return item

    result = assess([change(o) for o in items()])
    assert site(result, "t7").state is AllowlistSiteState.UNVERIFIED_PLACEMENT
    assert site(result, "t8").state is AllowlistSiteState.RESPONSE_REJECTED
    assert result.families[0].failed_hosts == 4


def test_network_change_cannot_conclude():
    result = assess(termination=DiagnosticTermination.NETWORK_CHANGED)
    assert result.verdict is AllowlistVerdict.INSUFFICIENT
    assert AllowlistReason.NETWORK_CHANGED in result.reasons


def test_all_repeat_successes_allow_only_scoped_no_pattern():
    every = [ok(o) for o in items()]
    assert assess(every).verdict is AllowlistVerdict.NO_PATTERN
    assert assess(every[:4]).verdict is AllowlistVerdict.INSUFFICIENT


def test_families_cannot_offset_and_inconsistent_waves_are_visible():
    split = [
        with_changes(o, address_family=AddressFamily.IPV6) if int(o.target_id[1:]) >= 3 else o
        for o in items()
    ]
    assert assess(split).verdict is AllowlistVerdict.INSUFFICIENT
    inconsistent = [ok(o) if o.target_id == "t8" and o.attempt == 2 else o for o in items()]
    assert site(assess(inconsistent), "t8").state is AllowlistSiteState.INCONSISTENT


def test_ipv6_does_not_participate():
    healthy = [ok(o) for o in items()]
    v6 = [
        with_changes(o, id=f"{o.id}-v6", address_family=AddressFamily.IPV6, evidence={})
        for o in items()
    ]
    assert assess(healthy + v6).verdict is AllowlistVerdict.NO_PATTERN


def test_all_confirmed_failures_mean_no_access():
    assert assess([failed(o) for o in items()]).verdict is AllowlistVerdict.NO_ACCESS


def test_common_success_with_failures_is_partial():
    mixed = [ok(o) if o.target_id == "t3" else o for o in items()]
    assert assess(mixed).verdict is AllowlistVerdict.PARTIAL_RESTRICTIONS


def test_unavailable_references_with_available_common_sites_are_partial():
    reversed_items = [failed(o) if int(o.target_id[1:]) < 3 else ok(o) for o in items()]
    assert assess(reversed_items).verdict is AllowlistVerdict.PARTIAL_RESTRICTIONS


def test_total_dns_outage_is_explained():
    dns = [
        ProbeObservation(
            f"{t.id}-dns-{resolver}", t.id, ProbeRoute.DIRECT, ProbeStage.DNS, ProbeStatus.FAILURE,
            failure_code=DiagnosticFailure.TIMEOUT, address_family=AddressFamily.IPV4,
            evidence={"resolver": resolver},
        )
        for t in TARGETS
        for resolver in ("system", "cloudflare-doh", "google-doh")
    ]  # fmt: skip
    skipped = [
        ProbeObservation(
            f"{t.id}-http", t.id, ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.SKIPPED,
            failure_code=DiagnosticFailure.DNS_FAILED, address_family=AddressFamily.IPV4,
        )
        for t in TARGETS
    ]  # fmt: skip
    result = assess(dns + skipped)
    assert result.verdict is AllowlistVerdict.NO_ACCESS
    assert result.dns_unavailable
    assert not assess().dns_unavailable


def test_third_success_resolves_unstable_reference():
    mixed = [
        failed(o, DiagnosticFailure.CONNECTION_RESET)
        if o.target_id == "t2" and o.attempt == 1
        else o
        for o in items()
    ]
    assert assess(mixed).verdict is AllowlistVerdict.INSUFFICIENT
    second = next(o for o in mixed if o.target_id == "t2" and o.attempt == 2)
    third = with_changes(second, id="t2-3", attempt=3)
    assert assess([*mixed, third]).verdict is AllowlistVerdict.POSSIBLE
    assert site(assess([*mixed, failed(third)]), "t2").state is AllowlistSiteState.INCONSISTENT


def test_duplicate_observation_of_one_wave_does_not_confirm():
    mixed = [failed(o) if o.target_id == "t2" and o.attempt == 1 else o for o in items()]
    second = next(o for o in mixed if o.target_id == "t2" and o.attempt == 2)
    duplicate = with_changes(second, id="duplicate-wave-2")
    assert assess([*mixed, duplicate]).verdict is AllowlistVerdict.INSUFFICIENT


def test_one_unavailable_reference_does_not_veto_independent_evidence():
    extra = DiagnosticTarget("ok", "ok.ru", TARGETS[0].placement_group)
    extras = [
        ProbeObservation(
            f"ok-{attempt}", "ok", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.FAILURE,
            attempt=attempt, failure_code=DiagnosticFailure.TIMEOUT,
            address_family=AddressFamily.IPV4, evidence={"placementGroup": extra.placement_group},
        )
        for attempt in (1, 2)
    ]  # fmt: skip
    catalog = DiagnosticCatalog(1, 1, 999_999, (*TARGETS, extra))
    result = assess_allowlist(report(items() + extras), catalog, CONTEXT)
    assert result.verdict is AllowlistVerdict.POSSIBLE
    assert result.families[0].sites[-1].state is AllowlistSiteState.SHARED_GROUP
    assert result.families[0].success_hosts == 3
    assert result.families[0].success_groups == 2


@pytest.mark.parametrize(
    ("second", "expected"),
    [
        (DiagnosticFailure.TIMEOUT, True),
        (DiagnosticFailure.HTTP_REJECTED, False),
    ],
)
def test_tie_break_needs_a_network_failure(second, expected):
    first = ProbeObservation(
        "a", "t", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.SUCCESS,
        address_family=AddressFamily.IPV4, evidence={"responseMatched": "true"},
    )  # fmt: skip
    other = with_changes(first, id="b", attempt=2, status=ProbeStatus.FAILURE, failure_code=second)
    assert needs_tie_break([first, other]) is expected
