from __future__ import annotations

import io
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.sys.windows.powershell import NrptSession


def test_nrpt_session_reuses_worker_and_preserves_json_payload(monkeypatch):
    session = NrptSession(timeout=0.01)
    stream = io.StringIO()
    process = SimpleNamespace(stdin=stream, poll=lambda: None)
    responses = queue.Queue()
    starts = []

    def start():
        starts.append(True)
        session._process, session._responses = process, responses

    monkeypatch.setattr(session, "_start", start)
    for _ in range(2):
        responses.put('{"ok": true, "output": "result"}')
        assert session.run("internal script") == "result"
    assert len(starts) == 1
    assert stream.getvalue().count('"script": "internal script"') == 2


@pytest.mark.parametrize("response", [None, '{"ok":false}', "not json", "timeout"])
def test_nrpt_failure_closes_worker_without_retry(monkeypatch, response):
    session = NrptSession(timeout=0.001)
    session._process = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    session._responses = queue.Queue()
    if response != "timeout":
        session._responses.put(response)
    close = Mock()
    monkeypatch.setattr(session, "_close", close)
    with pytest.raises(OSError, match="NRPT operation failed"):
        session.run("internal script")
    close.assert_called_once()


def test_close_reaps_worker_and_closes_streams():
    session = NrptSession()
    process = SimpleNamespace(kill=Mock(), wait=Mock(), stdin=io.StringIO(), stdout=io.StringIO())
    session._process = process
    session.close()
    process.kill.assert_called_once()
    process.wait.assert_called_once_with(timeout=2)
    assert process.stdin.closed and process.stdout.closed
    assert session._process is None
