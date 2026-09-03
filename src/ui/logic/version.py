"""Application and core version lookup.

Отдельный модуль, потому что версии показывают и настройки, и окно «О
программе»: две копии одной обработки ошибок разъезжаются.
"""

from __future__ import annotations

from typing import Any

UNKNOWN = "—"


def app_version() -> str:
    """Version of the application itself.

    Берётся из исходников, а не у установленного пакета: в AppImage пакет
    через pip не ставится, метаданных нет — и версия оборачивалась прочерком
    ровно там, где она нужнее всего. `cli.py bump-version` правит эту строку
    вместе с `pyproject.toml`, так что расхождения не будет.
    """
    try:
        import src

        return src.__version__
    except Exception:
        return UNKNOWN


def core_version(manager: Any | None) -> str:
    """Version of the xray core behind the application.

    Прочерк вместо исключения: ядра может не оказаться на месте, а диалог
    «О программе» обязан открыться в любом случае.
    """
    if manager is None:
        return UNKNOWN

    try:
        info = manager.get_version()
    except Exception:
        return UNKNOWN

    if not info:
        return UNKNOWN
    return str(info.get("version") or UNKNOWN)
