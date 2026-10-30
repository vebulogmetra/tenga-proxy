"""Главный цикл Qt как `MainLoop` (src/core/main_loop.py).

Монитор, контроллер и трей зовут `dispatch` из рабочих потоков. Сигнал с
`QueuedConnection` ставит вызов в очередь потока, которому принадлежит
объект; объект создаётся в главном потоке, поэтому вызов выполняется там.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot


@dataclass
class _TimerHandle:
    cancelled: Event = field(default_factory=Event)
    timer: QTimer | None = None


class QtLoop(QObject):
    """`dispatch`, `schedule` и `cancel` поверх очереди событий Qt.

    Создавать в главном потоке после `QApplication`: таймерам нужен цикл
    событий потока-владельца.
    """

    _call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)
        # Таймер без ссылки собрал бы сборщик мусора, и он молча остановился бы.
        self._timers: set[QTimer] = set()

    def dispatch(self, fn: Callable[..., object], *args: object) -> None:
        self._call.emit(lambda: fn(*args))

    @Slot(object)
    def _run(self, thunk: Callable[[], object]) -> None:
        thunk()

    def schedule(self, interval_ms: int, fn: Callable[[], bool]) -> object:
        handle = _TimerHandle()
        if QThread.currentThread() == self.thread():
            self._start_timer(handle, interval_ms, fn)
        else:
            self.dispatch(self._start_timer, handle, interval_ms, fn)
        return handle

    def _start_timer(self, handle: _TimerHandle, interval_ms: int, fn: Callable[[], bool]) -> None:
        # Подключение вызывает monitor.start() из рабочего потока. Создание
        # QTimer и управление им допустимы только в потоке-владельце QtLoop.
        if handle.cancelled.is_set():
            return
        timer = QTimer(self)
        handle.timer = timer
        timer.setInterval(interval_ms)

        def tick() -> None:
            if handle.cancelled.is_set() or not fn():
                self.cancel(handle)

        timer.timeout.connect(tick)
        self._timers.add(timer)
        timer.start()

    def cancel(self, handle: object) -> None:
        if not isinstance(handle, _TimerHandle):
            return
        handle.cancelled.set()
        if QThread.currentThread() == self.thread():
            self._stop_timer(handle)
        else:
            self.dispatch(self._stop_timer, handle)

    def _stop_timer(self, handle: _TimerHandle) -> None:
        timer = handle.timer
        if timer in self._timers:
            self._timers.discard(timer)
            timer.stop()
            timer.timeout.disconnect()
            timer.deleteLater()
        handle.timer = None
