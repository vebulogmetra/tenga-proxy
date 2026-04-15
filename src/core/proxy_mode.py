from __future__ import annotations

from typing import Any

from src.db.config import ProxyMode


def normalize_proxy_mode(mode: str | None) -> str:
    """Normalize runtime proxy mode."""
    if mode in ProxyMode.ALL:
        return mode
    return ProxyMode.TUN


def build_inbounds_for_mode(
    mode: str | None,
    *,
    address: str,
    socks_port: int,
    tun_name: str,
    tun_mtu: int,
) -> list[dict[str, Any]]:
    """Build xray inbounds according to selected runtime mode."""
    normalized_mode = normalize_proxy_mode(mode)

    if normalized_mode == ProxyMode.TUN:
        tun_ifname = (tun_name or "").strip() or "xray0"
        mtu = tun_mtu if 576 <= tun_mtu <= 9000 else 1500
        return [
            {
                "tag": "tun-in",
                "port": 0,
                "protocol": "tun",
                "settings": {
                    "name": tun_ifname,
                    "MTU": mtu,
                    "autoRoute": True,
                    "strictRoute": True,
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls"],
                },
            }
        ]

    return [
        {
            "listen": address,
            "port": socks_port,
            "protocol": "socks",
            "settings": {
                "auth": "noauth",
                "udp": True,
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls"],
            },
        },
        {
            "listen": address,
            "port": socks_port + 1,
            "protocol": "http",
            "settings": {},
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls"],
            },
        },
    ]


def should_manage_system_proxy(mode: str | None) -> bool:
    """Return True when desktop system proxy should be configured."""
    return normalize_proxy_mode(mode) == ProxyMode.SYSTEM_PROXY
