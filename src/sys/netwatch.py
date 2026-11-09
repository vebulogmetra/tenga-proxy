"""Отпечаток сети для восстановления после её смены. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.netwatch import default_route
else:
    from src.sys.linux.netwatch import default_route

__all__ = ["default_route"]
