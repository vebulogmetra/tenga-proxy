"""Чего не хватает для режима TUN. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.tun_access import tun_problems
else:
    from src.sys.linux.tun_access import tun_problems

__all__ = ["tun_problems"]
