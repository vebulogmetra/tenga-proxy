"""Маршруты TUN на Windows: их ставит и снимает служба Tenga Proxy."""

from __future__ import annotations

from dataclasses import dataclass

from src.sys.windows import service_client
from src.winsvc.state import ServiceError


@dataclass
class TunRouteState:
    tun_name: str
    proxy_ip: str


def apply_tun_routes(tun_name: str, proxy_host: str) -> tuple[bool, TunRouteState | None, str]:
    try:
        result = service_client.get_client().call(
            "routes.apply", tun_name=tun_name, proxy_host=proxy_host
        )
    except ServiceError as e:
        return False, None, str(e)
    return True, TunRouteState(tun_name=tun_name, proxy_ip=result.get("proxy_ip", "")), ""


def restore_tun_routes(state: TunRouteState | None) -> tuple[bool, str]:
    if state is None:
        return True, ""
    try:
        service_client.get_client().call("routes.restore")
    except ServiceError as e:
        return False, str(e)
    return True, ""


def recover_tun_routes() -> tuple[bool, str]:
    """Откат после падения делает служба при своём старте: клиенту делать нечего."""
    return True, ""
