"""Свежесть результата замера."""

from __future__ import annotations

from src.core.probe_result import PROBE_FRESH_SECONDS, is_fresh

NOW = 2_000_000_000.0


def test_recent_result_is_fresh():
    assert is_fresh(int(NOW - 60), NOW)


def test_result_at_the_boundary_is_stale():
    assert is_fresh(int(NOW - PROBE_FRESH_SECONDS + 1), NOW)
    assert not is_fresh(int(NOW - PROBE_FRESH_SECONDS), NOW)


def test_unknown_time_is_stale():
    assert not is_fresh(0, NOW)
