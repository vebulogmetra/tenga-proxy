"""DNS TUN-интерфейса на Windows. Настраивает служба (фаза 3 порта)."""

from __future__ import annotations

from src.core.proxy_mode import TUN_DNS_ADDRESS
from src.sys.windows.tun_route import NO_SERVICE

__all__ = ["TUN_DNS_ADDRESS", "route_system_dns_to_tun"]


def route_system_dns_to_tun(tun_name: str) -> tuple[bool, str]:
    return False, NO_SERVICE
