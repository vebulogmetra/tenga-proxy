"""Команда `diagnose`: итог в stdout, прогресс в stderr, отчёт — только по просьбе. Сети нет."""

from __future__ import annotations

import argparse
import json

import pytest

import cli
from src.diag.models import (
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.runner import Finished, ObservationEvent, Started


def _report(section=None, termination=DiagnosticTermination.COMPLETED) -> DiagnosticReport:
    item = ProbeObservation(
        "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS,
        evidence={"networkType": "ETHERNET", "vpnActive": "false"},
    )  # fmt: skip
    return DiagnosticReport(
        DiagnosticRunContext("run", "1", "1.2.3", section=section), (item,), termination=termination
    )


class FakeRunner:
    def __init__(self, termination=DiagnosticTermination.COMPLETED):
        self.termination = termination
        self.requests = []

    def run(self, request, on_event):
        self.requests.append(request)
        report = _report(request.section, self.termination)
        on_event(Started(report.context, ()))
        on_event(ObservationEvent(report.observations[0]))
        on_event(Finished(report))

    def cancel(self, reason=None):
        pass


@pytest.fixture
def runner(monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr("src.diag.runner.desktop_runner", lambda *_: fake)
    return fake


def _args(section="all", json_path=None):
    return argparse.Namespace(section=section, json=json_path)


def test_summary_goes_to_stdout_and_progress_to_stderr(runner, capsys):
    assert cli.cmd_diagnose(_args()) == 0
    captured = capsys.readouterr()
    assert "Сеть: Ethernet, Veblock отключён" in captured.out
    assert "Проверка завершена, проб: 1" in captured.out
    assert "." in captured.err
    assert "." not in captured.out.splitlines()[-1]


def test_cli_never_compares_through_the_tunnel(runner, capsys):
    cli.cmd_diagnose(_args())
    assert runner.requests[0].compare_active_tunnel is False


def test_section_is_passed_on(runner, capsys):
    cli.cmd_diagnose(_args("dns"))
    assert runner.requests[0].section is DiagnosticSection.DNS


def test_json_report_is_written_on_request(runner, capsys, tmp_path):
    path = tmp_path / "report.json"
    assert cli.cmd_diagnose(_args(json_path=str(path))) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["platform"]


def test_no_file_without_request(runner, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.cmd_diagnose(_args())
    assert list(tmp_path.iterdir()) == []


def test_partial_report_returns_nonzero(monkeypatch, capsys):
    fake = FakeRunner(DiagnosticTermination.USER_CANCELLED)
    monkeypatch.setattr("src.diag.runner.desktop_runner", lambda *_: fake)
    assert cli.cmd_diagnose(_args()) == 2
    assert "Проверка остановлена" in capsys.readouterr().out


def test_command_is_registered(runner, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["cli.py", "diagnose", "--section", "dns"])
    assert cli.main() == 0
    assert runner.requests[0].section is DiagnosticSection.DNS
