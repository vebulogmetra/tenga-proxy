"""Маршруты для режима TUN. Реализация выбирается по ОС."""

from src.sys.linux.tun_route import TunRouteState, apply_tun_routes, restore_tun_routes

__all__ = ["TunRouteState", "apply_tun_routes", "restore_tun_routes"]
