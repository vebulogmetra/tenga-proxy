"""VPN-подключения и сетевые интерфейсы. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.vpn import (
        connect_vpn,
        disconnect_vpn,
        get_default_interface,
        get_vpn_dns_servers,
        get_vpn_interface,
        get_vpn_interface_ip,
        is_vpn_active,
        list_network_interfaces,
        list_vpn_connections,
    )
else:
    from src.sys.linux.vpn import (
        connect_vpn,
        disconnect_vpn,
        get_default_interface,
        get_vpn_dns_servers,
        get_vpn_interface,
        get_vpn_interface_ip,
        is_vpn_active,
        list_network_interfaces,
        list_vpn_connections,
    )

__all__ = [
    "connect_vpn",
    "disconnect_vpn",
    "get_default_interface",
    "get_vpn_dns_servers",
    "get_vpn_interface",
    "get_vpn_interface_ip",
    "is_vpn_active",
    "list_network_interfaces",
    "list_vpn_connections",
]
