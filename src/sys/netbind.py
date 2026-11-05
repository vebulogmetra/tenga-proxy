"""Привязка сокета к физическому интерфейсу. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.netbind import (
        active_tunnel_interface,
        bind_socket,
        binding_confirmed,
        interface_addresses,
        interface_kind,
        physical_interface,
    )
else:
    from src.sys.linux.netbind import (
        active_tunnel_interface,
        bind_socket,
        binding_confirmed,
        interface_addresses,
        interface_kind,
        physical_interface,
    )

__all__ = [
    "active_tunnel_interface",
    "bind_socket",
    "binding_confirmed",
    "interface_addresses",
    "interface_kind",
    "physical_interface",
]
