"""DNS-серверы системы. Реализация выбирается по ОС."""

from src.sys.linux.resolver import system_dns_servers

__all__ = ["system_dns_servers"]
