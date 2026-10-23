"""DNS-серверы системы. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.resolver import system_dns_servers
else:
    from src.sys.linux.resolver import system_dns_servers

__all__ = ["system_dns_servers"]
