"""Сон и пробуждение на Linux приходят от logind по системной шине.

Шину слушает тулкит (`Gio.DBusConnection` в GTK, `QtDBus` в Qt), поэтому
системной подписки здесь нет: фасад отвечает None.
"""

from __future__ import annotations

from collections.abc import Callable


def subscribe(
    on_sleep: Callable[[], None], on_resume: Callable[[], None], dispatch: Callable[..., object]
) -> object | None:
    return None


def unsubscribe(subscription: object | None) -> None:
    return None
