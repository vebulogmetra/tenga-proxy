"""Главный цикл как зависимость: отложить в главный поток, таймер, отмена.

Монитор и контроллер интерфейса не знают, GLib это или Qt: им передают объект
с тремя методами. `GLibLoop` импортирует GLib лениво и при каждом вызове:
тесты монитора подменяют `gi.repository.GLib` через `sys.modules` и `patch`,
и подмена действует только на импорт в момент вызова. `ImmediateLoop`
выполняет всё сразу и нужен тестам без главного цикла.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

TimerFn = Callable[[], bool]


class MainLoop(Protocol):
    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        """Выполнить `fn(*args)` в главном потоке один раз."""

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        """Вызывать `fn` каждые `interval_ms`, пока она возвращает True."""

    def cancel(self, handle: object) -> None:
        """Снять таймер, выданный `schedule`."""


class GLibLoop:
    """Главный цикл GLib: `idle_add`, `timeout_add`, `source_remove`."""

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        from gi.repository import GLib

        def _once() -> bool:
            fn(*args)
            # Колбэк может вернуть что угодно (например, `save_config` — True);
            # без оболочки GLib повторял бы его как таймер.
            return GLib.SOURCE_REMOVE

        GLib.idle_add(_once)

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        from gi.repository import GLib

        return GLib.timeout_add(interval_ms, fn)

    def cancel(self, handle: object) -> None:
        from gi.repository import GLib

        GLib.source_remove(handle)


class ImmediateLoop:
    """Для тестов: `dispatch` выполняет сразу, таймеры срабатывают по `fire()`."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, TimerFn]] = []
        self.cancelled: list[object] = []

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        fn(*args)

    def schedule(self, interval_ms: int, fn: TimerFn) -> object:
        handle = (interval_ms, fn)
        self.scheduled.append(handle)
        return handle

    def cancel(self, handle: object) -> None:
        self.cancelled.append(handle)
        if handle in self.scheduled:
            self.scheduled.remove(handle)

    def fire(self) -> None:
        """Сработать всем таймерам по разу; вернувшие True остаются."""
        pending, self.scheduled = self.scheduled, []
        for handle in pending:
            if handle[1]():
                self.scheduled.append(handle)
