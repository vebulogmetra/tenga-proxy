"""Состояние окна диагностики: поддельный запуск вместо сети."""

from __future__ import annotations

import threading
import time

import pytest

from src.core.main_loop import ImmediateLoop
from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget
from src.diag.models import (
    AddressFamily,
    CauseAssessment,
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    FailureCause,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.runner import Finished, Started, Updated
from src.ui.logic.diagnostics_session import DiagnosticsSession


def _context(section=None) -> DiagnosticRunContext:
    return DiagnosticRunContext("run", "1", "1.2.3", section=section)


def _network(kind="WIFI") -> ProbeObservation:
    return ProbeObservation(
        "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS,
        evidence={"networkType": kind, "vpnActive": "false"},
    )  # fmt: skip


def _failed_http(target: str) -> ProbeObservation:
    return ProbeObservation(
        f"{target}-http", target, ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.FAILURE,
        address_family=AddressFamily.IPV4,
    )  # fmt: skip


def _target(target_id: str, purpose: DiagnosticPurpose):
    return type("T", (), {"id": target_id, "purpose": purpose})()


TARGETS = (_target("tg-web", DiagnosticPurpose.TELEGRAM_WEB),)


class FakeRunner:
    """Каждый run берёт следующий сценарий; `hold` держит запуск, пока тест его не отпустит."""

    def __init__(self, scripts, hold=None):
        self.scripts = list(scripts)
        self.hold = hold
        self.requests = []
        self.cancelled = []

    def run(self, request, on_event):
        self.requests.append(request)
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for event in script:
            on_event(event)
            if self.hold is not None:
                self.hold.wait(5)

    def cancel(self, reason=DiagnosticTermination.USER_CANCELLED):
        self.cancelled.append(reason)


def _session(runner) -> DiagnosticsSession:
    return DiagnosticsSession(ImmediateLoop(), lambda: runner)


def _finish(session, timeout=5.0):
    deadline = time.monotonic() + timeout
    while session.running:
        assert time.monotonic() < deadline, "проверка не завершилась"
        time.sleep(0.005)


def _main(section=None, *observations, termination=DiagnosticTermination.COMPLETED):
    report = DiagnosticReport(
        _context(section), (_network(), *observations), termination=termination
    )
    return [Started(_context(section), TARGETS), Updated(report), Finished(report)]


def test_start_runs_and_finishes():
    changes = []
    session = _session(FakeRunner([_main()]))
    session.on_changed = lambda: changes.append(session.running)
    assert session.can_start and not session.can_export
    assert session.start()
    _finish(session)
    assert session.report is not None
    assert not session.report.is_partial
    assert session.can_start and session.can_export and session.can_copy
    assert changes[0] is True
    assert changes[-1] is False


def test_second_start_is_refused_while_running():
    hold = threading.Event()
    session = _session(FakeRunner([_main()], hold=hold))
    assert session.start()
    assert session.start() is False
    assert session.can_stop
    hold.set()
    _finish(session)


def test_failed_targets_trigger_causes_run():
    causes = DiagnosticReport(
        _context(DiagnosticSection.DETAILS),
        (_network(),),
        cause_assessment=CauseAssessment({"tg-web": FailureCause.CONNECTION_FAILED}, 1),
    )
    runner = FakeRunner([_main(None, _failed_http("tg-web")), [Updated(causes), Finished(causes)]])
    session = _session(runner)
    session.start()
    _finish(session)
    assert runner.requests[1].section is DiagnosticSection.DETAILS
    assert runner.requests[1].detail_target_ids == {"tg-web"}
    assert runner.requests[1].compare_active_tunnel is False
    assert session.causes is causes
    assert not session.causes_running


def test_causes_from_another_network_are_dropped():
    causes = DiagnosticReport(_context(DiagnosticSection.DETAILS), (_network("ETHERNET"),))
    runner = FakeRunner([_main(None, _failed_http("tg-web")), [Finished(causes)]])
    session = _session(runner)
    session.start()
    _finish(session)
    assert session.causes is None


def test_no_causes_run_after_partial_report():
    runner = FakeRunner(
        [_main(None, _failed_http("tg-web"), termination=DiagnosticTermination.DEADLINE)]
    )
    session = _session(runner)
    session.start()
    _finish(session)
    assert len(runner.requests) == 1


def test_section_retry_keeps_other_reports():
    runner = FakeRunner([_main(), _main(DiagnosticSection.DNS)])
    session = _session(runner)
    session.start()
    _finish(session)
    first = session.report
    session.start(DiagnosticSection.DNS)
    _finish(session)
    assert runner.requests[1].section is DiagnosticSection.DNS
    assert session.report_for(DiagnosticSection.SERVICES) is first
    assert session.report_for(DiagnosticSection.DNS) is session.report
    assert session.is_previous(DiagnosticSection.SERVICES)
    assert not session.is_previous(DiagnosticSection.DNS)


def test_dns_retry_keeps_causes_and_runs_no_new_ones():
    causes = DiagnosticReport(_context(DiagnosticSection.DETAILS), (_network(),))
    runner = FakeRunner(
        [_main(None, _failed_http("tg-web")), [Finished(causes)], _main(DiagnosticSection.DNS)]
    )
    session = _session(runner)
    session.start()
    _finish(session)
    session.start(DiagnosticSection.DNS)
    _finish(session)
    assert session.causes is causes
    assert len(runner.requests) == 3


def test_full_restart_clears_previous_state():
    causes = DiagnosticReport(_context(DiagnosticSection.DETAILS), (_network(),))
    runner = FakeRunner([_main(None, _failed_http("tg-web")), [Finished(causes)], _main()])
    session = _session(runner)
    session.start()
    _finish(session)
    session.start()
    _finish(session)
    assert session.causes is None
    assert session.previous_reports == {}


def test_stop_marks_report_and_ignores_late_events():
    hold = threading.Event()
    runner = FakeRunner([_main()], hold=hold)
    session = _session(runner)
    session.start()
    deadline = time.monotonic() + 5
    while session.report is None:
        assert time.monotonic() < deadline
        time.sleep(0.005)
    session.stop()
    assert not session.running
    assert session.report.termination is DiagnosticTermination.USER_CANCELLED
    assert DiagnosticTermination.USER_CANCELLED in runner.cancelled
    hold.set()
    time.sleep(0.05)
    # Поздний Finished с COMPLETED не должен вернуть отчёт в завершённый.
    assert session.report.termination is DiagnosticTermination.USER_CANCELLED


def test_stop_before_started_still_shows_stopped_state():
    hold = threading.Event()

    class Blocked(FakeRunner):
        def run(self, request, on_event):
            hold.wait(5)

    session = _session(Blocked([]))
    session.start()
    session.stop()
    assert session.report.termination is DiagnosticTermination.USER_CANCELLED
    hold.set()


def test_close_cancels_and_silences_window():
    hold = threading.Event()
    calls = []
    runner = FakeRunner([_main()], hold=hold)
    session = _session(runner)
    session.on_changed = lambda: calls.append(1)
    session.start()
    count = len(calls)
    session.close()
    assert runner.cancelled
    hold.set()
    time.sleep(0.05)
    assert len(calls) == count


def test_runner_crash_marks_failed():
    report = DiagnosticReport(_context(), (_network(),))

    class Crashing(FakeRunner):
        def run(self, request, on_event):
            on_event(Started(_context(), TARGETS))
            on_event(Updated(report))
            raise RuntimeError("boom")

    session = _session(Crashing([]))
    session.start()
    _finish(session)
    assert session.failed
    assert session.report.termination is DiagnosticTermination.INTERNAL_ERROR


def test_events_are_drained_once_per_dispatch():
    class Deferred(ImmediateLoop):
        def __init__(self):
            super().__init__()
            self.queue = []

        def dispatch(self, fn, *args):
            self.queue.append((fn, args))

    loop = Deferred()
    calls = []
    session = DiagnosticsSession(loop, lambda: FakeRunner([_main()]))
    session.on_changed = lambda: calls.append(1)
    session.start()
    calls.clear()
    deadline = time.monotonic() + 5
    while not loop.queue and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.05)
    assert len(loop.queue) == 1
    fn, args = loop.queue.pop()
    fn(*args)
    assert len(calls) == 1
    assert not session.running


def test_export_writes_file(tmp_path):
    session = _session(FakeRunner([_main()]))
    session.start()
    _finish(session)
    assert session.export(tmp_path / "report.json")
    assert (tmp_path / "report.json").exists()


def test_export_failure_is_reported(tmp_path):
    session = _session(FakeRunner([_main()]))
    session.start()
    _finish(session)
    assert session.export(tmp_path / "missing" / "dir" / "report.json") is False


def test_summary_is_hidden_during_main_run():
    hold = threading.Event()
    session = _session(FakeRunner([_main()], hold=hold))
    session.start()
    assert session.summary() is None
    hold.set()
    _finish(session)
    assert session.summary() is not None


@pytest.mark.parametrize("section", [DiagnosticSection.ALLOWLIST, DiagnosticSection.SERVICES])
def test_section_run_also_explains_failures(section):
    causes = DiagnosticReport(_context(DiagnosticSection.DETAILS), (_network(),))
    targets = (_target("tg-web", DiagnosticPurpose.TELEGRAM_WEB),)
    main = DiagnosticReport(_context(section), (_network(), _failed_http("tg-web")))
    runner = FakeRunner([[Started(_context(section), targets), Finished(main)], [Finished(causes)]])
    session = _session(runner)
    session.start(section)
    _finish(session)
    if section is DiagnosticSection.SERVICES:
        assert len(runner.requests) == 2
    else:
        # В белых списках считаются только помощники: цель сервиса причин не запускает.
        assert len(runner.requests) == 1
