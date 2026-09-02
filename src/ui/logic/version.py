"""Application version lookup.

Отдельный модуль, потому что версию показывают и настройки, и окно «О
программе»: две копии одной обработки ошибок разъезжаются.
"""

from __future__ import annotations

UNKNOWN = "—"


def app_version() -> str:
    """Return the installed package version, or a dash in dev mode."""
    try:
        from importlib.metadata import version

        return version("tenga-proxy")
    except Exception:
        # В dev-режиме пакет может быть не установлен — версия не критична.
        return UNKNOWN
