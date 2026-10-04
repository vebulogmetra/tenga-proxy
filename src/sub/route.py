"""Через что загружать подписку."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.proxy_mode import normalize_proxy_mode
from src.db.config import ProxyMode

if TYPE_CHECKING:
    from src.core.context import ProxyState
    from src.db.data_store import DataStore

_WILDCARD_ADDRESSES = ("", "0.0.0.0", "::")


def local_proxy_url(config: DataStore, proxy_state: ProxyState) -> str | None:
    """Адрес локального HTTP-inbound, если подписку стоит качать через него.

    Сервер подписки часто заблокирован так же, как всё остальное. В режиме
    системного прокси ``requests`` настроек рабочего стола не видит и ходит
    напрямую, поэтому прокси ему нужно указать явно. В TUN запросы приложения
    и так идут через туннель — там ничего делать не нужно.
    """
    if not proxy_state.is_running:
        return None
    if normalize_proxy_mode(proxy_state.started_mode) != ProxyMode.SYSTEM_PROXY:
        return None

    address = (config.inbound_address or "").strip()
    if address in _WILDCARD_ADDRESSES:
        address = "127.0.0.1"
    if ":" in address and not address.startswith("["):
        address = f"[{address}]"
    # HTTP-inbound стоит на следующем порту после SOCKS (src/core/proxy_mode.py).
    return f"http://{address}:{config.inbound_socks_port + 1}"
