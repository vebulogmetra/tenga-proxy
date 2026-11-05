import threading

import pytest

from src.diag.budget import DiagnosticBudget, ScheduleSession
from src.diag.models import DiagnosticRequest


def test_attempts_and_bytes_are_limited_and_not_refunded():
    budget = DiagnosticBudget(3, 100)
    assert budget.reserve(60)
    assert not budget.reserve(41)
    assert budget.reserve(40)
    assert budget.reserve(0)
    assert not budget.reserve(0)


def test_budget_rejects_bad_values():
    with pytest.raises(ValueError):
        DiagnosticBudget(0, 1)
    with pytest.raises(ValueError):
        DiagnosticBudget(1, 1).reserve(-1)


def test_concurrent_reservations_do_not_exceed_limit():
    budget = DiagnosticBudget(100, 10**9)
    granted = []

    def worker():
        for _ in range(10):
            if budget.reserve(1):
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 100


def test_session_deadline_counts_down_to_zero():
    now = [1000]
    session = ScheduleSession(DiagnosticRequest(deadline_ms=500), clock=lambda: now[0])
    assert session.remaining_ms() == 500
    now[0] = 1600
    assert session.remaining_ms() == 0
