"""Главный цикл как зависимость: GLib и мгновенная реализация для тестов."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core.main_loop import GLibLoop, ImmediateLoop


def test_immediate_loop_dispatches_right_away():
    loop = ImmediateLoop()
    seen = []

    loop.dispatch(seen.append, 1)

    assert seen == [1]


def test_immediate_loop_keeps_repeating_timers_and_drops_finished_ones():
    loop = ImmediateLoop()
    ticks = []
    loop.schedule(100, lambda: ticks.append("a") or True)
    loop.schedule(200, lambda: ticks.append("b") or False)

    loop.fire()
    loop.fire()

    assert ticks == ["a", "b", "a"]


def test_immediate_loop_cancel_removes_the_timer():
    loop = ImmediateLoop()
    ticks = []
    handle = loop.schedule(100, lambda: ticks.append(1) or True)

    loop.cancel(handle)
    loop.fire()

    assert ticks == []
    assert loop.cancelled == [handle]


def _fake_glib():
    calls = []
    glib = SimpleNamespace(
        SOURCE_REMOVE=False,
        idle_add=lambda fn, *args: calls.append(("idle", fn, args)) or 7,
        timeout_add=lambda ms, fn: calls.append(("timeout", ms, fn)) or 8,
        source_remove=lambda handle: calls.append(("remove", handle)) or True,
    )
    return glib, calls


def test_glib_loop_imports_glib_lazily_and_wraps_dispatch():
    glib, calls = _fake_glib()
    repository = SimpleNamespace(GLib=glib)
    loop = GLibLoop()
    seen = []

    with patch.dict(sys.modules, {"gi.repository": repository, "gi.repository.GLib": glib}):
        loop.dispatch(seen.append, "x")
        kind, once, args = calls[-1]
        # Оболочка возвращает SOURCE_REMOVE, что бы ни вернул колбэк.
        assert kind == "idle" and args == ()
        assert once() is False
        assert seen == ["x"]

        assert loop.schedule(150, lambda: True) == 8
        assert calls[-1] == ("timeout", 150, calls[-1][2])

        loop.cancel(8)
        assert calls[-1] == ("remove", 8)


def test_glib_loop_schedule_passes_the_callback_positionally():
    """Тесты монитора читают `call[0][1]`: порядок аргументов — часть контракта."""
    glib, calls = _fake_glib()
    repository = SimpleNamespace(GLib=glib)

    with patch.dict(sys.modules, {"gi.repository": repository, "gi.repository.GLib": glib}):
        GLibLoop().schedule(10, print)

    assert calls == [("timeout", 10, print)]


@pytest.mark.parametrize("name", ["dispatch", "schedule", "cancel"])
def test_main_loop_protocol_names(name):
    assert hasattr(ImmediateLoop(), name)
    assert hasattr(GLibLoop(), name)
