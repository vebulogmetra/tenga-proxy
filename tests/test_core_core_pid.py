"""Осиротевшее ядро: приложение упало, xray остался с TUN и маршрутами."""

from __future__ import annotations

import signal
import sys

import pytest

from src.core import core_pid

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="нужны /proc и SIGKILL")

BINARY = "/usr/lib/tenga-proxy/core/bin/xray"


@pytest.fixture
def process(monkeypatch):
    """Подменный процесс 4242: что за бинарник и какие сигналы получил."""

    class Process:
        binary: str | None = BINARY
        signals: list[int] = []
        ignores_term = False

    Process.signals = []
    monkeypatch.setattr(core_pid.os.path, "realpath", lambda path: path)

    def kill(_pid, sig):
        Process.signals.append(sig)
        if sig == signal.SIGKILL or not Process.ignores_term:
            Process.binary = None

    monkeypatch.setattr(core_pid, "_process_binary", lambda _pid: Process.binary)
    monkeypatch.setattr(core_pid.os, "kill", kill)
    monkeypatch.setattr(core_pid.time, "sleep", lambda _s: None)
    return Process


def test_orphan_with_our_binary_is_terminated(process):
    core_pid.remember(4242, BINARY)

    assert core_pid.kill_orphan() is True

    assert process.signals == [signal.SIGTERM]
    assert not core_pid.PID_FILE.exists()


def test_orphan_ignoring_sigterm_is_killed(process):
    process.ignores_term = True
    core_pid.remember(4242, BINARY)

    assert core_pid.kill_orphan() is True

    assert process.signals == [signal.SIGTERM, signal.SIGKILL]


def test_reused_pid_of_another_program_is_left_alone(process):
    process.binary = "/usr/bin/firefox"
    core_pid.remember(4242, BINARY)

    assert core_pid.kill_orphan() is False

    assert process.signals == []
    assert not core_pid.PID_FILE.exists()


def test_finished_process_is_only_forgotten(process):
    process.binary = None
    core_pid.remember(4242, BINARY)

    assert core_pid.kill_orphan() is False

    assert process.signals == []
    assert not core_pid.PID_FILE.exists()


def test_missing_pidfile_is_fine():
    assert core_pid.kill_orphan() is False


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"pid": "x", "binary": "/a"}', "[1]"])
def test_broken_pidfile_is_dropped(text, process):
    core_pid.PID_FILE.write_text(text)

    assert core_pid.kill_orphan() is False

    assert process.signals == []
    assert not core_pid.PID_FILE.exists()


def test_binary_replaced_by_a_package_upgrade_still_counts(monkeypatch):
    """После обновления пакета ссылка /proc/<pid>/exe кончается на « (deleted)»."""
    monkeypatch.setattr(core_pid.os, "readlink", lambda _path: f"{BINARY} (deleted)")

    assert core_pid._process_binary(4242) == BINARY


def test_process_without_proc_entry_has_no_binary(monkeypatch):
    def gone(_path):
        raise FileNotFoundError

    monkeypatch.setattr(core_pid.os, "readlink", gone)

    assert core_pid._process_binary(4242) is None
