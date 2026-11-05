import threading

import pytest

from src.core.http_probe import ProbeCredentials, ProbeEndpoint
from src.diag.catalog import DiagnosticCatalog, DiagnosticPurpose, DiagnosticTarget
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    DiagnosticReport,
    DiagnosticRequest,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.network import DirectPolicy, NetworkState
from src.diag.runner import (
    DesktopEnvironment,
    DiagnosticRunChange,
    DiagnosticRunner,
    DiagnosticSources,
    Finished,
    ObservationEvent,
    Started,
    Updated,
    causes_request,
    context_sources,
    failed_target_ids,
    same_network,
)
from src.diag.scheduler import DiagnosticTask, SocketRegistry


def task(task_id, route=ProbeRoute.DIRECT, block=None):
    def execute():
        if block:
            block()
        return ProbeObservation(task_id, "target", route, ProbeStage.HTTP, ProbeStatus.SUCCESS)

    return DiagnosticTask(task_id, "target", "origin", route, ProbeStage.HTTP, 1, execute)


class Environment:
    verified_placement_groups = frozenset()
    allowlist_complete = False
    services_started = False
    services_complete = False
    dns_started = False
    dns_complete = False
    compare_services_through_tunnel = True

    def __init__(self, phases, targets=()):
        self.catalog = DiagnosticCatalog(1, 1, 100, tuple(targets))
        self.phases = phases
        self.changes = []
        self.closed = False
        self.sockets = (SocketRegistry(),)
        self.lost = False

    def tasks(self, phase, _observations):
        return self.phases[phase] if phase < len(self.phases) else None

    def follow_up_tasks(self, _phase, _observations):
        return []

    def phase_completed(self, _phase):
        pass

    def poll_change(self):
        return self.changes.pop(0) if self.changes else None

    def tunnel_lost(self):
        self.lost = True

    def close(self):
        self.closed = True


def run(environment, **request):
    runner = DiagnosticRunner(lambda _r: environment, "1.2.3", epoch_seconds=lambda: 1)
    events = []
    runner.run(DiagnosticRequest(**request), events.append)
    return events


def finished(events):
    return next(e for e in events if isinstance(e, Finished)).report


def test_events_are_ordered_and_environment_closes():
    environment = Environment([[task("a")], [task("b")]])
    events = run(environment)
    assert isinstance(events[0], Started)
    assert isinstance(events[-1], Finished)
    assert [e.observation.id for e in events if isinstance(e, ObservationEvent)] == ["a", "b"]
    assert any(isinstance(e, Updated) for e in events)
    assert len(finished(events).observations) == 2
    assert environment.closed


def test_runner_refuses_a_second_concurrent_run():
    gate = threading.Event()
    entered = threading.Event()

    def block():
        entered.set()
        gate.wait(5)

    runner = DiagnosticRunner(lambda _r: Environment([[task("a", block=block)]]), "1")
    worker = threading.Thread(target=runner.run, args=(DiagnosticRequest(), lambda _e: None))
    worker.start()
    assert entered.wait(2)
    with pytest.raises(RuntimeError, match="already"):
        runner.run(DiagnosticRequest(), lambda _e: None)
    gate.set()
    worker.join(2)


def test_cancel_finishes_with_user_cancelled_and_keeps_results():
    gate = threading.Event()
    entered = threading.Event()

    def block():
        entered.set()
        gate.wait(5)

    environment = Environment([[task("done")], [task("slow", block=block)], [task("never")]])
    runner = DiagnosticRunner(lambda _r: environment, "1")
    events = []
    worker = threading.Thread(target=runner.run, args=(DiagnosticRequest(), events.append))
    worker.start()
    assert entered.wait(2)
    runner.cancel()
    worker.join(2)
    gate.set()
    assert not worker.is_alive()
    report = finished(events)
    assert report.termination is DiagnosticTermination.USER_CANCELLED
    items = {o.id: o for o in report.observations}
    assert items["done"].status is ProbeStatus.SUCCESS
    assert items["slow"].status is ProbeStatus.CANCELLED
    assert items["slow"].failure_code is DiagnosticFailure.USER_CANCELLED
    assert "never" not in items
    assert environment.closed


def test_network_change_stops_the_run():
    gate = threading.Event()
    environment = Environment([[task("a")], [task("slow", block=lambda: gate.wait(5))]])
    environment.changes = [DiagnosticRunChange.NETWORK_CHANGED]
    events = run(environment)
    gate.set()
    report = finished(events)
    assert report.termination is DiagnosticTermination.NETWORK_CHANGED
    assert next(o for o in report.observations if o.id == "a").status is ProbeStatus.SUCCESS


def test_vpn_change_cancels_tunnel_while_direct_continues():
    gate = threading.Event()

    def direct():
        gate.wait(3)

    environment = Environment(
        [
            [
                task("direct", block=direct),
                task("tunnel", ProbeRoute.ACTIVE_TUNNEL, block=lambda: threading.Event().wait(30)),
            ]
        ]
    )
    original = environment.tunnel_lost

    def lost():
        original()
        gate.set()

    environment.tunnel_lost = lost
    environment.changes = [DiagnosticRunChange.VPN_SESSION_CHANGED]
    report = finished(run(environment))
    items = {o.id: o for o in report.observations}
    assert items["direct"].status is ProbeStatus.SUCCESS
    assert items["tunnel"].failure_code is DiagnosticFailure.VPN_SESSION_CHANGED
    assert environment.lost


def test_budget_survives_phases_and_failures_do_not_kill_siblings():
    def boom():
        raise RuntimeError("secret")

    environment = Environment([[task("bad", block=boom)], [task("good"), task("skip")]])
    report = finished(run(environment, max_attempts=2))
    items = {o.id: o for o in report.observations}
    assert items["bad"].failure_code is DiagnosticFailure.IO
    assert report.coverage.successful == 1
    assert report.coverage.skipped == 1
    assert "secret" not in str(report)


def test_large_plans_retain_budget_skips():
    environment = Environment([[task(f"probe-{i}") for i in range(200)]])
    report = finished(run(environment, max_attempts=2))
    assert report.termination is DiagnosticTermination.COMPLETED
    assert report.coverage.successful == 2
    assert report.coverage.skipped == 198


def test_deadline_is_a_termination():
    gate = threading.Event()
    environment = Environment([[task("slow", block=lambda: gate.wait(5))]])
    report = finished(run(environment, deadline_ms=50))
    gate.set()
    assert report.termination is DiagnosticTermination.DEADLINE


def test_catalog_version_and_targets_come_from_the_environment():
    target = DiagnosticTarget("target", "example.org", "group")
    events = run(Environment([[task("one")]], [target]))
    assert next(e for e in events if isinstance(e, Started)).targets == (target,)
    report = finished(events)
    assert report.context.catalog_version == "1"
    assert "CATALOG_STALE" not in [f.code for f in report.findings]


def test_expired_catalog_is_reported():
    runner = DiagnosticRunner(
        lambda _r: Environment([[task("one")]]), "1.2.3", epoch_seconds=lambda: 1_000
    )
    events = []
    runner.run(DiagnosticRequest(), events.append)
    assert "CATALOG_STALE" in [f.code for f in finished(events).findings]


def test_open_failure_becomes_internal_error_without_details():
    def fail(_request):
        raise ValueError("bad catalog at 10.0.0.1")

    events = []
    DiagnosticRunner(fail, "1").run(DiagnosticRequest(), events.append)
    report = finished(events)
    assert report.termination is DiagnosticTermination.INTERNAL_ERROR
    assert report.observations[0].id == "run-error"
    assert "10.0.0.1" not in str(report)


@pytest.mark.parametrize("section", list(DiagnosticSection))
def test_section_reports_contain_only_their_assessment(section):
    report = finished(run(Environment([[]]), section=section))
    assert report.context.section is section
    assert (report.allowlist_assessment is not None) == (section is DiagnosticSection.ALLOWLIST)
    assert (report.service_assessment is not None) == (section is DiagnosticSection.SERVICES)
    assert (report.dns_assessment is not None) == (section is DiagnosticSection.DNS)
    assert (report.cause_assessment is not None) == (section is DiagnosticSection.DETAILS)


def http(target_id, status, attempt=1, route=ProbeRoute.DIRECT, failure=None):
    return ProbeObservation(
        f"{target_id}-{attempt}-{route.name}", target_id, route, ProbeStage.HTTP, status,
        attempt=attempt, failure_code=failure, address_family=AddressFamily.IPV4,
    )  # fmt: skip


def report_of(*items, **kwargs):
    return DiagnosticReport(DiagnosticRunContext("r", "1", "1.0.0"), items, **kwargs)


def test_failed_targets_need_no_success_at_all():
    targets = [
        DiagnosticTarget("a", "a.example", "g"),
        DiagnosticTarget("b", "b.example", "g"),
        DiagnosticTarget("c", "c.example", "g", purpose=DiagnosticPurpose.TELEGRAM_WEB),
    ]
    report = report_of(
        http("a", ProbeStatus.FAILURE),
        http("b", ProbeStatus.SUCCESS),
        http("b", ProbeStatus.FAILURE, attempt=2),
        http("c", ProbeStatus.SKIPPED),
    )
    assert failed_target_ids(report, targets) == {"a", "c"}


def test_causes_request_is_separate_and_short():
    request = causes_request(frozenset({"a"}))
    assert request.section is DiagnosticSection.DETAILS
    assert request.deadline_ms == 60_000
    assert not request.compare_active_tunnel


def test_same_network_rejects_changed_or_broken_causes():
    def network(kind):
        return ProbeObservation(
            "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS,
            evidence={"networkType": kind, "vpnActive": "false"},
        )  # fmt: skip

    main = report_of(network("WIFI"))
    assert same_network(main, report_of(network("WIFI")))
    assert not same_network(main, report_of(network("ETHERNET")))
    changed = report_of(network("WIFI"), termination=DiagnosticTermination.NETWORK_CHANGED)
    assert not same_network(main, changed)


STATE = NetworkState("eth0", "ETHERNET", ("192.0.2.10",), DirectPolicy())


@pytest.fixture
def sources(monkeypatch):
    # Настоящая сеть в тестах не трогается: снимок подменён, проб нет.
    monkeypatch.setattr("src.diag.runner.read_network_state", lambda _policy: STATE)
    return DiagnosticSources(DirectPolicy, lambda: None)


def test_no_network_reports_only_the_baseline(monkeypatch, sources):
    empty = NetworkState(None, "OTHER", (), DirectPolicy())
    monkeypatch.setattr("src.diag.runner.read_network_state", lambda _policy: empty)
    environment = DesktopEnvironment(DiagnosticRequest(), sources)
    tasks = environment.tasks(0, [])
    assert [t.id for t in tasks] == ["network"]
    assert tasks[0].execute().failure_code is DiagnosticFailure.NO_NETWORK
    assert environment.tasks(1, []) is None


def test_kill_switch_skips_direct_without_io(monkeypatch):
    blocked = NetworkState("eth0", "ETHERNET", ("192.0.2.10",), DirectPolicy("xray0", True))
    monkeypatch.setattr("src.diag.runner.read_network_state", lambda _policy: blocked)
    environment = DesktopEnvironment(
        DiagnosticRequest(), DiagnosticSources(lambda: blocked.policy, lambda: None)
    )
    for phase in (1, 2):
        for item in environment.tasks(phase, []):
            result = item.execute()
            assert result.status in (ProbeStatus.SKIPPED,)
    dns = environment.tasks(1, [])[0].execute()
    assert dns.failure_code is DiagnosticFailure.SYSTEM_RESTRICTED
    network = environment.tasks(0, [])[0].execute()
    assert network.status is ProbeStatus.SUCCESS
    assert network.evidence["vpnActive"] == "true"


def test_without_a_session_tunnel_tasks_skip(sources):
    environment = DesktopEnvironment(DiagnosticRequest(), sources)
    tunnel = [t for t in environment.tasks(5, []) if t.route is ProbeRoute.ACTIVE_TUNNEL]
    assert tunnel
    result = tunnel[0].execute()
    assert result.status is ProbeStatus.SKIPPED
    assert result.failure_code is DiagnosticFailure.PROXY_UNAVAILABLE


class FakeProxyState:
    is_running = True
    started_mode = "tun"
    traffic_blocked = False
    health_endpoint = ProbeEndpoint(1234, ProbeCredentials("u", "p"))


class FakeSettings:
    tun_name = "tun7"
    tun_kill_switch = True


class FakeContext:
    proxy_state = FakeProxyState()
    config = FakeSettings()


def test_context_sources_read_the_session():
    sources = context_sources(FakeContext())
    assert sources.policy() == DirectPolicy("tun7", True)
    assert sources.endpoint().port == 1234
    stopped = FakeContext()
    stopped.proxy_state = type("S", (FakeProxyState,), {"is_running": False})()
    assert context_sources(stopped).policy() == DirectPolicy(None, False)


def test_network_change_is_polled(monkeypatch, sources):
    environment = DesktopEnvironment(DiagnosticRequest(), sources)
    environment._next_network_check = 0
    assert environment.poll_change() is None
    other = NetworkState("wlan0", "WIFI", ("192.0.2.20",), DirectPolicy())
    monkeypatch.setattr(environment._watcher, "_read", lambda _policy: other)
    environment._next_network_check = 0
    assert environment.poll_change() is DiagnosticRunChange.NETWORK_CHANGED
