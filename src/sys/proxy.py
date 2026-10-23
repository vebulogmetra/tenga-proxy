"""Системный прокси. Реализация выбирается по ОС, имена одни и те же."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.proxy import clear_system_proxy, set_system_proxy
else:
    from src.sys.linux.proxy import clear_system_proxy, set_system_proxy

__all__ = ["clear_system_proxy", "set_system_proxy"]
