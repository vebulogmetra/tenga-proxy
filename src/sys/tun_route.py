"""Маршруты для режима TUN. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.tun_route import (
        TunRouteState,
        apply_tun_routes,
        recover_tun_routes,
        restore_tun_routes,
    )
else:
    from src.sys.linux.tun_route import (
        TunRouteState,
        apply_tun_routes,
        recover_tun_routes,
        restore_tun_routes,
    )

__all__ = ["TunRouteState", "apply_tun_routes", "recover_tun_routes", "restore_tun_routes"]
