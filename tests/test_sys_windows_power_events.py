"""Коды событий питания Windows."""

from __future__ import annotations

from src.sys.windows import power_events


def test_suspend_and_both_resume_codes_are_recognised():
    assert power_events.classify(power_events.PBT_APMSUSPEND) == "sleep"
    assert power_events.classify(power_events.PBT_APMRESUMEAUTOMATIC) == "resume"
    assert power_events.classify(power_events.PBT_APMRESUMESUSPEND) == "resume"
    assert power_events.classify(0x000A) is None  # смена источника питания


def test_unsubscribe_ignores_a_missing_subscription():
    power_events.unsubscribe(None)
