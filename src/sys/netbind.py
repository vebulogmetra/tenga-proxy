"""Привязка сокета к физическому интерфейсу. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.netbind import (
        bind_socket,
        binding_confirmed,
        interface_addresses,
        interface_kind,
        physical_interface,
    )
else:
    from src.sys.linux.netbind import (
        bind_socket,
        binding_confirmed,
        interface_addresses,
        interface_kind,
        physical_interface,
    )

__all__ = [
    "bind_socket",
    "binding_confirmed",
    "interface_addresses",
    "interface_kind",
    "physical_interface",
]
