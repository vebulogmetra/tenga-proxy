"""Главный цикл Qt как `MainLoop` (src/core/main_loop.py).

Монитор, контроллер и трей зовут `dispatch` из рабочих потоков. Сигнал с
`QueuedConnection` ставит вызов в очередь потока, которому принадлежит
объект; объект создаётся в главном потоке, поэтому вызов выполняется там.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot


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
        timer = QTimer(self)
        timer.setInterval(interval_ms)

        def tick() -> None:
            if not fn():
                self.cancel(timer)

        timer.timeout.connect(tick)
        self._timers.add(timer)
        timer.start()
        return timer

    def cancel(self, handle: object) -> None:
        if handle in self._timers:
            self._timers.discard(handle)
            handle.stop()
            handle.deleteLater()
