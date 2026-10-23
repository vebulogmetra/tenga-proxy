"""Защита от второго экземпляра. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.single_instance import SingleInstance
else:
    from src.sys.linux.single_instance import SingleInstance

__all__ = ["SingleInstance"]
