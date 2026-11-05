from dataclasses import dataclass

from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose, DiagnosticTarget, load_catalog
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    DiagnosticRequest,
    DiagnosticSection,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.plan import DiagnosticProbePlan, with_changes

V4 = (AddressFamily.IPV4,)
BASELINE = DiagnosticTarget("baseline", "example.org", "group-a", expected_body="ok", families=V4)
SERVICE = DiagnosticTarget(
    "service", "example.com", "group-b", purpose=DiagnosticPurpose.TELEGRAM_APP, families=V4
)
CATALOG = DiagnosticCatalog(1, 1, 100, (BASELINE, SERVICE))
DNS_CATALOG = DiagnosticCatalog(
    1,
    1,
    100,
    (
        DiagnosticTarget("google-web", "www.google.com", "google", families=V4),
        DiagnosticTarget(
            "youtube-web", "www.youtube.com", "google",
            purpose=DiagnosticPurpose.YOUTUBE_WEB, families=V4,
        ),
        DiagnosticTarget(
            "telegram-web", "web.telegram.org", "telegram",
            purpose=DiagnosticPurpose.TELEGRAM_WEB, families=V4,
        ),
        DiagnosticTarget(
            "instagram-web", "www.instagram.com", "meta",
            purpose=DiagnosticPurpose.INSTAGRAM_WEB, families=V4,
        ),
    ),
)  # fmt: skip


@dataclass
class Dns:
    observation: ProbeObservation
    addresses: tuple[str, ...]


class Backend:
    def __init__(self):
        self.calls = []
        self.tunnel_calls = 0

    def extended_tasks(self):
        return []

    def baseline(self):
        return ProbeObservation(
            "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS
        )

    def dns(self, id, target, family, resolver):
        self.calls.append(f"dns:{target.id}")
        ok = resolver != "system"
        return Dns(
            ProbeObservation(
                id, target.id, ProbeRoute.DIRECT, ProbeStage.DNS,
                ProbeStatus.SUCCESS if ok else ProbeStatus.FAILURE,
                address_family=family, evidence={"resolver": resolver},
            ),
            ("1.1.1.1",) if ok else (),
        )  # fmt: skip

    def connection(self, id, target, stage, route, address):
        self.calls.append(f"connect:{target.id}")
        if route is ProbeRoute.ACTIVE_TUNNEL:
            self.tunnel_calls += 1
        return ProbeObservation(id, target.id, route, stage, ProbeStatus.SUCCESS)


class AnswerBackend(Backend):
    def __init__(self, system, doh):
        super().__init__()
        self.system = system
        self.doh = doh

    def dns(self, id, target, family, resolver):
        address = (self.system if resolver == "system" else self.doh).get(target.id)
        return Dns(
            ProbeObservation(
                id, target.id, ProbeRoute.DIRECT, ProbeStage.DNS,
                ProbeStatus.FAILURE if address is None else ProbeStatus.SUCCESS,
                address_family=family, evidence={"resolver": resolver},
            ),
            () if address is None else (address,),
        )  # fmt: skip


def consistency(plan):
    for phase in range(8):
        for task in plan.tasks(phase, []):
            task.execute()
    return {t.target_id: t.execute().evidence for t in plan.follow_up_tasks(7, [])}


def run_all(plan, phases=range(9)):
    observations = []
    tasks = []
    for phase in phases:
        batch = plan.tasks(phase, observations) or []
        tasks.extend(batch)
        observations.extend(task.execute() for task in batch)
    return tasks, observations


def test_stub_address_shared_across_owners_and_absent_from_doh_is_flagged():
    plan = DiagnosticProbePlan(
        DNS_CATALOG,
        DiagnosticRequest(),
        AnswerBackend(
            {"google-web": "142.250.1.1", "youtube-web": "195.1.1.1", "telegram-web": "195.1.1.1"},
            {
                "google-web": "142.250.1.1",
                "youtube-web": "142.250.2.2",
                "telegram-web": "149.154.1.1",
            },
        ),
    )
    evidence = consistency(plan)
    assert evidence["google-web"]["dohOverlap"] == "full"
    assert evidence["google-web"]["sharedAnswer"] == "false"
    assert evidence["telegram-web"]["dohOverlap"] == "none"
    assert evidence["telegram-web"]["sharedAnswer"] == "true"
    assert evidence["youtube-web"]["sharedAnswer"] == "true"
    assert not any("." in value for item in evidence.values() for value in item.values())


def test_shared_address_within_one_owner_is_not_a_stub():
    plan = DiagnosticProbePlan(
        DNS_CATALOG,
        DiagnosticRequest(),
        AnswerBackend(
            {
                "google-web": "142.250.9.9",
                "youtube-web": "142.250.9.9",
                "telegram-web": "149.154.1.1",
            },
            {
                "google-web": "142.250.1.1",
                "youtube-web": "142.250.2.2",
                "telegram-web": "149.154.1.1",
            },
        ),
    )
    assert consistency(plan)["youtube-web"]["sharedAnswer"] == "false"


def test_instagram_keeps_doh_fallback_but_leaves_the_dns_stage():
    plan = DiagnosticProbePlan(DNS_CATALOG, DiagnosticRequest(), AnswerBackend({}, {}))
    assert any(t.id == "instagram-web-ipv4-dns-cloudflare-doh" for t in plan.tasks(4, []))
    assert not any(t.target_id == "instagram-web" for t in plan.tasks(7, []))
    assert not any(t.target_id == "instagram-web" for t in plan.follow_up_tasks(7, []))


def test_allowlist_retry_does_not_compute_dns_consistency():
    plan = DiagnosticProbePlan(
        DNS_CATALOG, DiagnosticRequest(section=DiagnosticSection.ALLOWLIST), AnswerBackend({}, {})
    )
    assert plan.follow_up_tasks(7, []) == []


def test_baseline_connections_precede_service_dns_and_keep_resolver_provenance():
    backend = Backend()
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(), backend)
    _, observations = run_all(plan, range(6))
    assert backend.calls.index("connect:baseline") < backend.calls.index("dns:service")
    http = next(
        o
        for o in observations
        if o.target_id == "baseline" and o.stage is ProbeStage.HTTP and o.route is ProbeRoute.DIRECT
    )
    assert http.evidence["resolver"] == "cloudflare-doh"
    assert backend.tunnel_calls == 1
    assert not any(o.stage in (ProbeStage.QUIC, ProbeStage.QUALITY) for o in observations)


def test_no_tunnel_calls_when_comparison_is_disabled():
    backend = Backend()
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(compare_active_tunnel=False), backend)
    run_all(plan, range(6))
    assert backend.tunnel_calls == 0


def test_dns_work_uses_resolver_origin_for_shared_limits():
    tasks = DiagnosticProbePlan(CATALOG, DiagnosticRequest(), Backend()).tasks(1, [])
    assert any(t.origin == "cloudflare-doh" for t in tasks)
    assert any(t.origin == "google-doh" for t in tasks)
    assert all(t.max_bytes >= 16656 for t in tasks)


def test_baseline_success_is_confirmed_before_service_dns():
    backend = Backend()
    _, observations = run_all(DiagnosticProbePlan(CATALOG, DiagnosticRequest(), backend))
    http = [
        o
        for o in observations
        if o.target_id == "baseline" and o.stage is ProbeStage.HTTP and o.route is ProbeRoute.DIRECT
    ]
    assert {o.attempt for o in http} == {1, 2}
    connects = [i for i, call in enumerate(backend.calls) if call == "connect:baseline"]
    assert connects[3] < backend.calls.index("dns:service")


def test_service_stage_finishes_before_later_stages():
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(), Backend())
    assert not plan.services_started
    plan.phase_completed(3)
    assert plan.allowlist_complete
    assert plan.services_started
    assert not plan.services_complete
    assert all(t.target_id != "baseline" for t in plan.tasks(5, []))
    assert all(t.stage is ProbeStage.HTTP for t in plan.tasks(5, []))
    assert [t.id for t in plan.tasks(6, [])] == ["service-ipv4-http-2"]
    plan.phase_completed(6)
    assert plan.services_complete
    assert plan.tasks(8, []) == []


def test_bundled_reservations_fit_the_payload_budget():
    request = DiagnosticRequest()
    plan = DiagnosticProbePlan(load_catalog(), request, Backend())
    tasks, _ = run_all(plan)
    assert sum(t.max_bytes for t in tasks) <= request.max_payload_bytes
    assert len(tasks) <= request.max_attempts


def test_dns_stage_follows_services_and_marks_second_attempt():
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(), Backend())
    assert not plan.dns_started
    plan.phase_completed(6)
    assert plan.dns_started
    tasks = plan.tasks(7, [])
    assert {t.id for t in tasks} == {"baseline-ipv4-dns-system-2", "service-ipv4-dns-system-2"}
    results = [t.execute() for t in tasks]
    assert all(r.attempt == 2 and r.address_family is AddressFamily.IPV4 for r in results)
    plan.phase_completed(7)
    assert plan.dns_complete


def test_allowlist_retry_excludes_services_and_deep_probes():
    plan = DiagnosticProbePlan(
        CATALOG, DiagnosticRequest(section=DiagnosticSection.ALLOWLIST), Backend()
    )
    tasks, _ = run_all(plan)
    assert all(t.target_id != "service" for t in tasks)
    assert all(t.route is not ProbeRoute.ACTIVE_TUNNEL for t in tasks)
    assert any(t.id == "baseline-ipv4-http-2" for t in tasks)


def test_service_retry_resolves_fresh_dependencies_without_baseline():
    plan = DiagnosticProbePlan(
        CATALOG, DiagnosticRequest(section=DiagnosticSection.SERVICES), Backend()
    )
    tasks, _ = run_all(plan)
    ids = {t.id for t in tasks}
    assert all(t.target_id != "baseline" for t in tasks)
    assert {"service-ipv4-dns-system", "service-ipv4-http-2", "service-tunnel"} <= ids


def test_dns_retry_has_no_resource_connections():
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(section=DiagnosticSection.DNS), Backend())
    tasks = [t for phase in range(9) for t in plan.tasks(phase, []) or []]
    assert all(t.stage in (ProbeStage.NETWORK, ProbeStage.DNS) for t in tasks)
    assert sum(t.stage is ProbeStage.DNS for t in tasks) == 8


def test_only_contradictory_baseline_gets_a_third_attempt():
    plan = DiagnosticProbePlan(
        CATALOG, DiagnosticRequest(section=DiagnosticSection.ALLOWLIST), Backend()
    )
    mixed = [
        ProbeObservation(
            "baseline-ipv4-http-1", "baseline", ProbeRoute.DIRECT, ProbeStage.HTTP,
            ProbeStatus.SUCCESS, address_family=AddressFamily.IPV4,
            evidence={"responseMatched": "true"},
        ),
        ProbeObservation(
            "baseline-ipv4-http-2", "baseline", ProbeRoute.DIRECT, ProbeStage.HTTP,
            ProbeStatus.FAILURE, attempt=2, failure_code=DiagnosticFailure.TIMEOUT,
            address_family=AddressFamily.IPV4,
        ),
    ]  # fmt: skip
    assert [t.id for t in plan.follow_up_tasks(3, mixed)] == ["baseline-ipv4-http-3"]
    assert plan.follow_up_tasks(2, mixed) == []
    third = with_changes(mixed[0], id="baseline-ipv4-http-3", attempt=3)
    assert plan.follow_up_tasks(3, [*mixed, third]) == []
    same = [with_changes(o, status=ProbeStatus.SUCCESS) for o in mixed]
    assert plan.follow_up_tasks(3, same) == []


def test_details_probe_failed_targets_and_controls_without_tunnel():
    yandex = DiagnosticTarget("yandex-main", "yandex.ru", "yandex", families=V4)
    catalog = DiagnosticCatalog(1, 1, 100, (*CATALOG.targets, yandex))
    full = DiagnosticProbePlan(catalog, DiagnosticRequest(), Backend())
    assert full.tasks(8, []) == []
    details = DiagnosticProbePlan(
        catalog,
        DiagnosticRequest(
            section=DiagnosticSection.DETAILS, detail_target_ids=frozenset({"service"})
        ),
        Backend(),
    )
    tasks = [t for phase in range(9) for t in details.tasks(phase, []) or []]
    assert all(t.target_id != "baseline" for t in tasks)
    assert all(t.route is not ProbeRoute.ACTIVE_TUNNEL for t in tasks)
    assert not any(t.stage is ProbeStage.HTTP for t in tasks)
    deep = [t for t in tasks if t.stage in (ProbeStage.TCP, ProbeStage.TLS)]
    assert {t.target_id for t in deep} == {"service", "yandex-main"}
    assert len(deep) == 8


def test_connection_without_dns_answer_is_skipped():
    plan = DiagnosticProbePlan(CATALOG, DiagnosticRequest(), AnswerBackend({}, {}))
    observation = plan.tasks(2, [])[0].execute()
    assert observation.status is ProbeStatus.SKIPPED
    assert observation.failure_code is DiagnosticFailure.DNS_FAILED
