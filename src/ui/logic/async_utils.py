"""Run work off the GTK main loop and deliver the result back onto it.

Модуль не импортирует GTK: результат доставляется через `dispatch`, по
умолчанию через `GLib.idle_add`. Тесты подставляют список вместо очереди.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("tenga.ui.async")

DispatchFn = Callable[..., object]


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


def run_in_background(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    *,
    dispatch: DispatchFn = _default_dispatch,
    name: str = "tenga-worker",
) -> threading.Thread:
    """Call `fn` in a daemon thread, hand the outcome to the main loop.

    Возвращает поток, чтобы тесты могли его дождаться. Ошибка без `on_error`
    только пишется в лог: поток не должен падать молча.
    """

    def _worker() -> None:
        try:
            result = fn()
        # BaseException: KeyboardInterrupt в рабочем потоке иначе исчезнет
        # вместе с ним, не дойдя ни до лога, ни до вызывающего кода.
        except BaseException as e:
            logger.exception("Background task %s failed: %s", name, e)
            if on_error is not None:
                dispatch(on_error, e)
            return

        if on_done is not None:
            dispatch(on_done, result)

    thread = threading.Thread(target=_worker, name=name, daemon=True)
    thread.start()
    return thread
