"""Системный прокси Windows: ключ `Internet Settings` пользователя и WinINet.

Значения читают WinINet (Edge, Chrome, большинство программ) и WinHTTP-клиенты,
импортирующие настройки пользователя. После записи WinINet нужно уведомить, иначе
уже запущенные программы увидят изменение только после перезапуска.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tenga.sys.proxy")

KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

# Адреса, которые не должны идти через прокси: локальные сети и имена без точки.
BYPASS = ";".join(
    [
        "localhost",
        "127.*",
        "10.*",
        *(f"172.{octet}.*" for octet in range(16, 32)),
        "192.168.*",
        "<local>",
    ]
)


class _UserRegistry:
    def write(self, values: dict[str, object]) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind, value)


def _notify_wininet() -> None:
    import ctypes

    wininet = ctypes.WinDLL("wininet")
    wininet.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
    wininet.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0)


def proxy_values(http_port: int, socks_port: int, address: str = "127.0.0.1") -> dict[str, object]:
    """Значения реестра. Вход ядра смешанный, поэтому одного HTTP-адреса достаточно."""
    if 0 < http_port < 65536:
        server = f"{address}:{http_port}"
    else:
        # `socks=` WinINet понимает как SOCKS4; ядро его принимает.
        server = f"socks={address}:{socks_port}"
    return {"ProxyEnable": 1, "ProxyServer": server, "ProxyOverride": BYPASS}


def _apply(values: dict[str, object], registry, notify) -> bool:
    try:
        (registry or _UserRegistry()).write(values)
        (notify or _notify_wininet)()
        return True
    except OSError as e:
        logger.error("Cannot change Windows proxy settings: %s", e)
        return False


def set_system_proxy(
    http_port: int = 0,
    socks_port: int = 0,
    address: str = "127.0.0.1",
    *,
    registry=None,
    notify=None,
) -> bool:
    has_http = 0 < http_port < 65536
    has_socks = 0 < socks_port < 65536
    if not has_http and not has_socks:
        return False
    return _apply(proxy_values(http_port, socks_port, address), registry, notify)


def clear_system_proxy(*, registry=None, notify=None) -> bool:
    return _apply({"ProxyEnable": 0}, registry, notify)
