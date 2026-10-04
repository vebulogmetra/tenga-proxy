from __future__ import annotations

from typing import Any

from src.db.config import ProxyMode

# quic обязателен: браузеры ходят по HTTP/3, и без него ядро не извлекает домен
# из udp:443 — доменные правила маршрутизации для такого трафика молча не работают.
SNIFFING_DEST_OVERRIDE = ("http", "tls", "quic")

TUN_INBOUND_TAG = "tun-in"
# Адрес TUN-интерфейса. Нужен только systemd-resolved: через интерфейс без
# маршрутизируемого адреса он запросы не шлёт. Диапазон 198.18.0.0/15 отведён
# под стенды и в настоящих сетях не встречается.
TUN_ADDRESS = "198.18.0.1/30"


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
    tun_address: str | None = None,
) -> list[dict[str, Any]]:
    """Build xray inbounds according to selected runtime mode.

    `tun_address` — адрес, который ядро назначит TUN-интерфейсу (поле `gateway`).
    """
    normalized_mode = normalize_proxy_mode(mode)

    if normalized_mode == ProxyMode.TUN:
        tun_ifname = (tun_name or "").strip() or "xray0"
        mtu = tun_mtu if 576 <= tun_mtu <= 9000 else 1500
        settings: dict[str, Any] = {
            "name": tun_ifname,
            "MTU": mtu,
            "autoRoute": True,
            "strictRoute": True,
        }
        if tun_address:
            settings["gateway"] = [tun_address]
        return [
            {
                "tag": TUN_INBOUND_TAG,
                "port": 0,
                "protocol": "tun",
                "settings": settings,
                "sniffing": {
                    "enabled": True,
                    "destOverride": list(SNIFFING_DEST_OVERRIDE),
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
                "destOverride": list(SNIFFING_DEST_OVERRIDE),
            },
        },
        {
            "listen": address,
            "port": socks_port + 1,
            "protocol": "http",
            "settings": {},
            "sniffing": {
                "enabled": True,
                "destOverride": list(SNIFFING_DEST_OVERRIDE),
            },
        },
    ]


def should_manage_system_proxy(mode: str | None) -> bool:
    """Return True when desktop system proxy should be configured."""
    return normalize_proxy_mode(mode) == ProxyMode.SYSTEM_PROXY
