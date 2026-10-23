"""DNS TUN-интерфейса на Windows: адрес и правило NRPT ставит служба.

Снимать нечего: служба откатывает DNS вместе с маршрутами и ядром.
"""

from __future__ import annotations

from src.core.proxy_mode import TUN_DNS_ADDRESS
from src.sys.windows import service_client
from src.winsvc.state import ServiceError

__all__ = ["TUN_DNS_ADDRESS", "route_system_dns_to_tun"]


def route_system_dns_to_tun(tun_name: str) -> tuple[bool, str]:
    try:
        service_client.get_client().call("dns.apply", tun_name=tun_name)
    except ServiceError as e:
        return False, str(e)
    return True, ""
