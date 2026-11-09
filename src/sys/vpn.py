"""VPN-подключения и сетевые интерфейсы. Реализация выбирается по ОС."""

from src.core.platform_info import IS_WINDOWS

if IS_WINDOWS:
    from src.sys.windows.vpn import (
        companion_vpn_supported,
        connect_vpn,
        disconnect_vpn,
        get_default_interface,
        get_vpn_dns_servers,
        get_vpn_interface,
        get_vpn_interface_ip,
        is_vpn_active,
        list_network_interfaces,
        list_vpn_connections,
        vpn_connection_type,
        vpn_server_addresses,
        vpn_tunnel_interface,
    )
else:
    from src.sys.linux.vpn import (
        companion_vpn_supported,
        connect_vpn,
        disconnect_vpn,
        get_default_interface,
        get_vpn_dns_servers,
        get_vpn_interface,
        get_vpn_interface_ip,
        is_vpn_active,
        list_network_interfaces,
        list_vpn_connections,
        vpn_connection_type,
        vpn_server_addresses,
        vpn_tunnel_interface,
    )

__all__ = [
    "companion_vpn_supported",
    "connect_vpn",
    "disconnect_vpn",
    "get_default_interface",
    "get_vpn_dns_servers",
    "get_vpn_interface",
    "get_vpn_interface_ip",
    "is_vpn_active",
    "list_network_interfaces",
    "list_vpn_connections",
    "vpn_connection_type",
    "vpn_server_addresses",
    "vpn_tunnel_interface",
]
