"""Сон и пробуждение системы. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.power_events import subscribe, unsubscribe
else:
    from src.sys.linux.power_events import subscribe, unsubscribe

__all__ = ["subscribe", "unsubscribe"]
