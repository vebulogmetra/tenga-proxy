"""Системный DNS через TUN. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.tun_dns import TUN_DNS_ADDRESS, route_system_dns_to_tun
else:
    from src.sys.linux.tun_dns import TUN_DNS_ADDRESS, route_system_dns_to_tun

__all__ = ["TUN_DNS_ADDRESS", "route_system_dns_to_tun"]
