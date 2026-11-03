"""Блокировка трафика мимо туннеля. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.tun_firewall import apply_firewall, remove_firewall
else:
    from src.sys.linux.tun_firewall import apply_firewall, remove_firewall

__all__ = ["apply_firewall", "remove_firewall"]
