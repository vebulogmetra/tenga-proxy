import dataclasses

import pytest

from src.diag.models import (
    CauseAssessment,
    DiagnosticFailure,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticRequest,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    EvidenceLevel,
    FailureCause,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)


def obs(**kw):
    base = {
        "id": "o1",
        "target_id": "t",
        "route": ProbeRoute.DIRECT,
        "stage": ProbeStage.HTTP,
        "status": ProbeStatus.SUCCESS,
    }
    base.update(kw)
    return ProbeObservation(**base)


CTX = DiagnosticRunContext("run", "6", "0.25.0")


def test_observation_rejects_unknown_evidence_key():
    with pytest.raises(ValueError, match=r".+"):
        obs(evidence={"ipAddress": "1.2.3.4"})


def test_observation_rejects_long_or_control_values():
    with pytest.raises(ValueError, match=r".+"):
        obs(evidence={"alpn": "x" * 129})
    with pytest.raises(ValueError, match=r".+"):
        obs(evidence={"alpn": "h2\n"})


def test_observation_attempt_bounds():
    with pytest.raises(ValueError, match=r".+"):
        obs(attempt=0)
    with pytest.raises(ValueError, match=r".+"):
        obs(attempt=4)
    assert obs(attempt=3).attempt == 3


def test_observation_http_status_bounds():
    with pytest.raises(ValueError, match=r".+"):
        obs(http_status=99)
    assert obs(http_status=204).http_status == 204


def test_observation_needs_ids_and_non_negative_elapsed():
    with pytest.raises(ValueError, match=r".+"):
        obs(id=" ")
    with pytest.raises(ValueError, match=r".+"):
        obs(elapsed_ms=-1)


def test_request_limits_match_android():
    request = DiagnosticRequest()
    assert (request.deadline_ms, request.max_attempts, request.max_payload_bytes) == (
        120_000, 384, 8 * 1024 * 1024,
    )  # fmt: skip
    with pytest.raises(ValueError, match=r".+"):
        DiagnosticRequest(deadline_ms=120_001)
    with pytest.raises(ValueError, match=r".+"):
        DiagnosticRequest(detail_target_ids={f"t{i}" for i in range(33)})
    with pytest.raises(ValueError, match=r".+"):
        DiagnosticRequest(detail_target_ids={"Bad Id"})


def test_sections_phases():
    assert DiagnosticSection.ALLOWLIST.phases == frozenset({0, 1, 2, 3})
    assert DiagnosticSection.SERVICES.phases == frozenset({0, 4, 5, 6})
    assert DiagnosticSection.DNS.phases == frozenset({0, 1, 4, 7})
    assert DiagnosticSection.DETAILS.phases == frozenset({0, 1, 4, 8})
    assert DiagnosticRequest().phases == frozenset(range(8))


def test_failure_codes_are_the_android_set():
    assert len(DiagnosticFailure) == 28
    assert all(item.value == item.name for item in DiagnosticFailure)


def test_report_rejects_duplicate_ids_and_foreign_findings():
    with pytest.raises(ValueError, match=r".+"):
        DiagnosticReport(CTX, (obs(), obs()))
    finding = DiagnosticFinding("X", EvidenceLevel.OBSERVED, ("missing",))
    with pytest.raises(ValueError, match=r".+"):
        DiagnosticReport(CTX, (obs(),), (finding,))


def test_report_partial_and_coverage():
    report = DiagnosticReport(
        CTX,
        (obs(), obs(id="o2", status=ProbeStatus.FAILURE), obs(id="o3", status=ProbeStatus.SKIPPED)),
        termination=DiagnosticTermination.DEADLINE,
    )
    assert report.is_partial
    assert dataclasses.astuple(report.coverage) == (1, 1, 0, 1, 0, 0)


def test_network_facts_read_baseline_without_failure():
    report = DiagnosticReport(
        CTX,
        (
            obs(
                id="network", target_id="network", stage=ProbeStage.NETWORK,
                evidence={"networkType": "WIFI", "vpnActive": "true"},
            ),
        ),
    )  # fmt: skip
    facts = report.network_facts()
    assert (facts.type, facts.vpn_active) == ("WIFI", True)
    assert DiagnosticReport(CTX).network_facts() is None


def test_top_causes_keep_ties_in_enum_order():
    assessment = CauseAssessment(
        {"a": FailureCause.TLS_FAILED, "b": FailureCause.CONNECTION_FAILED, "c": FailureCause.CERTIFICATE},
        3,
    )  # fmt: skip
    assert assessment.top_cause_count == 1
    assert assessment.top_causes == (
        FailureCause.CONNECTION_FAILED, FailureCause.TLS_FAILED, FailureCause.CERTIFICATE,
    )  # fmt: skip
    assert CauseAssessment().top_causes == ()
