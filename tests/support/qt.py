"""Ожидание событий Qt в тестах без pytest-qt.

pytest-qt не подходит: без установленного PySide6 его плагин роняет весь
pytest, а обычный прогон и CI Linux идут без Qt.
"""

from __future__ import annotations

import time
from collections.abc import Callable


def process_events() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    """Крутить цикл событий, пока условие не выполнится; иначе AssertionError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process_events()
        if predicate():
            return
        time.sleep(0.01)
    process_events()
    assert predicate(), "условие не выполнилось за отведённое время"
