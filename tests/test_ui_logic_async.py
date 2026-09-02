"""Tests for the background-thread helper."""

from __future__ import annotations

import logging

from src.ui.logic.async_utils import run_in_background


def _collector():
    """Dispatch stub that records calls instead of touching the GTK main loop."""
    calls: list[tuple] = []

    def dispatch(fn, *args):
        calls.append((fn, args))

    return calls, dispatch


def _drain(calls):
    for fn, args in calls:
        fn(*args)


def test_result_reaches_on_done():
    calls, dispatch = _collector()
    done: list[int] = []

    thread = run_in_background(lambda: 42, on_done=done.append, dispatch=dispatch)
    thread.join(5)
    _drain(calls)

    assert done == [42]


def test_exception_reaches_on_error():
    calls, dispatch = _collector()
    errors: list[BaseException] = []
    boom = ValueError("boom")

    def fail():
        raise boom

    thread = run_in_background(fail, on_error=errors.append, dispatch=dispatch)
    thread.join(5)
    _drain(calls)

    assert errors == [boom]


def test_on_done_is_not_called_on_failure():
    calls, dispatch = _collector()
    done: list[object] = []

    def fail():
        raise ValueError("boom")

    thread = run_in_background(fail, on_done=done.append, dispatch=dispatch)
    thread.join(5)
    _drain(calls)

    assert done == []


def test_failure_without_on_error_is_logged(caplog):
    calls, dispatch = _collector()

    def fail():
        raise ValueError("boom")

    with caplog.at_level(logging.ERROR, logger="tenga.ui.async"):
        thread = run_in_background(fail, dispatch=dispatch)
        thread.join(5)

    assert not thread.is_alive()
    assert "boom" in caplog.text


def test_base_exception_is_caught_too():
    calls, dispatch = _collector()
    errors: list[BaseException] = []

    def fail():
        raise KeyboardInterrupt

    thread = run_in_background(fail, on_error=errors.append, dispatch=dispatch)
    thread.join(5)
    _drain(calls)

    assert isinstance(errors[0], KeyboardInterrupt)


def test_without_callbacks_nothing_is_dispatched():
    calls, dispatch = _collector()

    thread = run_in_background(lambda: 1, dispatch=dispatch)
    thread.join(5)

    assert calls == []


def test_thread_is_a_named_daemon():
    calls, dispatch = _collector()

    thread = run_in_background(lambda: None, dispatch=dispatch, name="probe")
    thread.join(5)

    assert thread.daemon is True
    assert thread.name == "probe"
