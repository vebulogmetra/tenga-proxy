from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger("tenga.sys.vpn")


def is_vpn_active(connection_name: str) -> bool:
    """
    Check if VPN connection is active in NetworkManager.
    
    Args:
        connection_name: Name of the VPN connection in NetworkManager
        
    Returns:
        True if VPN is active
    """
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0:
            active_connections = result.stdout.strip().split("\n")
            return connection_name in active_connections
        
        return False
    except FileNotFoundError:
        logger.warning("nmcli not found, cannot check VPN status")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Timeout checking VPN status")
        return False
    except Exception as e:
        logger.error("Error checking VPN status: %s", e)
        return False


def get_vpn_interface(connection_name: str) -> Optional[str]:
    """
    Get VPN interface name for active connection.
    
    Args:
        connection_name: Name of the VPN connection in NetworkManager
        
    Returns:
        Interface name
    """
    if not is_vpn_active(connection_name):
        return None
    
    try:
        # Get device name from nmcli
        result = subprocess.run(
            ["nmcli", "-t", "-f", "GENERAL.DEVICE", "connection", "show", connection_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0:
            device = result.stdout.strip()
            if device and device != "--":
                return device
        
        #check active connection device
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE", "connection", "show", "--active", connection_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0:
            device = result.stdout.strip()
            if device and device != "--":
                return device
        
        # tun/tap interfaces
        result = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "tun" in line or "tap" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        interface = parts[1].strip().split("@")[0].strip()
                        if interface.startswith(("tun", "tap")):
                            return interface
        
        return None
    except FileNotFoundError:
        logger.warning("nmcli or ip not found, cannot determine VPN interface")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Timeout determining VPN interface")
        return None
    except Exception as e:
        logger.error("Error determining VPN interface: %s", e)
        return None


def get_vpn_interface_ip(interface_name: str) -> Optional[str]:
    """
    Get IP address of VPN interface.
    
    Args:
        interface_name: Name of the VPN interface
        
    Returns:
        IP address or None if not found
    """
    if not interface_name:
        return None
    
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", interface_name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "inet " in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        ip_with_cidr = parts[1]
                        ip = ip_with_cidr.split("/")[0]
                        return ip
        
        return None
    except FileNotFoundError:
        logger.warning("ip command not found, cannot get VPN interface IP")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Timeout getting VPN interface IP")
        return None
    except Exception as e:
        logger.error("Error getting VPN interface IP: %s", e)
        return None
