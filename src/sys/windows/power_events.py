"""Сон и пробуждение Windows без окна: `PowerRegisterSuspendResumeNotification`.

`WM_POWERBROADCAST` получают только окна верхнего уровня, а окно Qt создаётся
лениво: приложение в трее может жить без него. Обратный вызов приходит из
системного потока, поэтому `on_sleep` и `on_resume` вызываются через `dispatch`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger("tenga.sys.windows.power_events")

DEVICE_NOTIFY_CALLBACK = 2
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

Dispatch = Callable[..., object]


def classify(event: int) -> str | None:
    """Код события питания: «sleep», «resume» или None — нас не касается."""
    if event == PBT_APMSUSPEND:
        return "sleep"
    # Автоматическое пробуждение приходит всегда, «по действию пользователя» — вслед
    # за ним; лишний вызов гасит само восстановление.
    if event in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
        return "resume"
    return None


class PowerSubscription:
    """Подписка; держит ссылку на обратный вызов, иначе его собрал бы сборщик мусора."""

    def __init__(self, handle: object, callback: object, params: object) -> None:
        self.handle = handle
        self._callback = callback
        self._params = params


def subscribe(
    on_sleep: Callable[[], None], on_resume: Callable[[], None], dispatch: Dispatch
) -> PowerSubscription | None:
    """Подписаться на сон и пробуждение; None — система не дала подписку."""
    try:
        import ctypes
        from ctypes import wintypes

        callback_type = ctypes.WINFUNCTYPE(
            wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p
        )

        class _Params(ctypes.Structure):
            _fields_ = [("Callback", callback_type), ("Context", ctypes.c_void_p)]

        def routine(_context, event, _setting) -> int:
            kind = classify(int(event))
            if kind == "sleep":
                dispatch(on_sleep)
            elif kind == "resume":
                dispatch(on_resume)
            return 0

        callback = callback_type(routine)
        params = _Params(callback, None)
        handle = ctypes.c_void_p()
        powrprof = ctypes.WinDLL("powrprof")
        status = powrprof.PowerRegisterSuspendResumeNotification(
            DEVICE_NOTIFY_CALLBACK, ctypes.byref(params), ctypes.byref(handle)
        )
    except (AttributeError, OSError) as e:
        logger.info("Suspend/resume notifications are unavailable: %s", e)
        return None
    if status != 0:
        logger.info("PowerRegisterSuspendResumeNotification failed: %s", status)
        return None
    return PowerSubscription(handle, callback, params)


def unsubscribe(subscription: object | None) -> None:
    if not isinstance(subscription, PowerSubscription):
        return
    try:
        import ctypes

        ctypes.WinDLL("powrprof").PowerUnregisterSuspendResumeNotification(subscription.handle)
    except (AttributeError, OSError) as e:
        logger.debug("Could not unsubscribe from power events: %s", e)
