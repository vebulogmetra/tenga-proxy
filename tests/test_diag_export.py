import json
import re

from src.diag.export import encode_report, export_filename, write_report
from src.diag.models import (
    DiagnosticFailure,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    EvidenceLevel,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)

SECRET = "secret-password-ssid-192.168.1.1"
CONTEXT = DiagnosticRunContext("a37bcb35-c050-485b-b3be-ec921ae65121", "2", "1.4.5")


def test_whitelist_removes_identifiers_and_freeform_evidence():
    observations = tuple(
        ProbeObservation(
            f"{SECRET}-{i}", f"https://subscription.test/{SECRET}", ProbeRoute.DIRECT,
            ProbeStage.HTTP, status,
            evidence={"coverage": "x"},
        )
        for i, status in enumerate(ProbeStatus)
    )  # fmt: skip
    finding = DiagnosticFinding(SECRET, EvidenceLevel.OBSERVED, (observations[0].id,), (SECRET,))
    report = DiagnosticReport(
        CONTEXT, observations, (finding,), DiagnosticTermination.USER_CANCELLED
    )
    output = encode_report(report)
    assert SECRET not in output
    assert "subscription.test" not in output
    assert CONTEXT.run_id not in output
    assert not re.search(r"\d+\.\d+\.\d+\.\d+", output)
    parsed = json.loads(output)
    assert parsed["schemaVersion"] == 2
    assert parsed["platform"] in ("linux", "windows")
    assert [o["status"] for o in parsed["observations"]] == [s.name for s in ProbeStatus]
    assert parsed["termination"] == "USER_CANCELLED"
    assert parsed["observations"][0]["target"] == "t1"
    assert parsed["observations"][0]["id"] == "o1"


def test_public_target_labels_survive():
    report = DiagnosticReport(
        CONTEXT,
        (
            ProbeObservation(
                "one", "telegram-web", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.SUCCESS
            ),
        ),
    )
    assert "telegram-web" in encode_report(report)


def test_dns_evidence_survives_without_addresses():
    report = DiagnosticReport(
        CONTEXT,
        (
            ProbeObservation(
                "c", "youtube-web", ProbeRoute.DIRECT, ProbeStage.DNS, ProbeStatus.SUCCESS,
                evidence={
                    "coverage": "answer-consistency", "dohOverlap": "none", "sharedAnswer": "true",
                },
            ),
            ProbeObservation(
                "n", "google-dns", ProbeRoute.DIRECT, ProbeStage.UDP, ProbeStatus.SUCCESS,
                evidence={"coverage": "dns-nxdomain", "dohOverlap": "192.0.2.1"},
            ),
        ),
    )  # fmt: skip
    text = encode_report(report)
    assert "answer-consistency" in text
    assert '"dohOverlap": "none"' in text
    assert "192.0.2.1" not in text


def test_section_is_exported():
    report = DiagnosticReport(
        DiagnosticRunContext("run", "2", "1.4.5", section=DiagnosticSection.DNS)
    )
    assert json.loads(encode_report(report))["section"] == "DNS"


def test_causes_share_target_tokens():
    def probe(target):
        return ProbeObservation(
            "same-id", target, ProbeRoute.DIRECT, ProbeStage.TCP, ProbeStatus.FAILURE,
            failure_code=DiagnosticFailure.TIMEOUT, evidence={"resolver": "192.0.2.1"},
        )  # fmt: skip

    main = DiagnosticReport(CONTEXT, (probe("private-target"),))
    causes = DiagnosticReport(CONTEXT, (probe("private-target"),))
    parsed = json.loads(encode_report(main, causes))
    assert parsed["observations"][0]["id"] == "o1"
    nested = parsed["causes"]["observations"][0]
    assert nested["id"] == "c1"
    assert nested["target"] == parsed["observations"][0]["target"]
    assert "private-target" not in json.dumps(parsed)


def test_too_many_observations_are_truncated_with_a_mark():
    observations = tuple(
        ProbeObservation(
            f"o-{i}", "network", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.SUCCESS
        )
        for i in range(1100)
    )
    parsed = json.loads(encode_report(DiagnosticReport(CONTEXT, observations)))
    assert len(parsed["observations"]) == 1024
    assert parsed["truncated"] is True


def test_filename_and_atomic_write(tmp_path):
    report = DiagnosticReport(CONTEXT)
    assert export_filename(report) == "veblock-diagnostics-a37bcb35.json"
    path = tmp_path / export_filename(report)
    write_report(path, report)
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 2
    assert [p.name for p in tmp_path.iterdir()] == [path.name]
