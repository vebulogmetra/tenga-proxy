"""Monitoring page summary (GTK-free).

Признак активности VPN приходит параметром, а не вычисляется здесь: проверка
идёт через NetworkManager, и тесты этого модуля иначе лезли бы в систему.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

UNKNOWN = "—"
NOT_SET = "не задан"
NOT_CONFIGURED = "не настроен"

_PROXY_ALL = "proxy_all"
_TIME_FORMAT = "%H:%M:%S"

CLASS_OK = "status-connected"
CLASS_ERROR = "status-error"
CLASS_DIM = "dim-label"


@dataclass(frozen=True)
class MonitoringRow:
    """One labelled value on the monitoring page."""

    title: str
    value: str
    css_class: str = ""


@dataclass(frozen=True)
class MonitoringView:
    """Everything the monitoring page renders."""

    connection: tuple[MonitoringRow, ...]
    routing: tuple[MonitoringRow, ...]
    last_check: str


def format_last_check(timestamp: float) -> str:
    """Render the time of the last check, including the "never" case."""
    if not timestamp:
        return UNKNOWN
    return datetime.datetime.fromtimestamp(timestamp).strftime(_TIME_FORMAT)


def _blank_routing() -> tuple[MonitoringRow, ...]:
    return tuple(
        MonitoringRow(title=title, value=UNKNOWN, css_class=CLASS_DIM)
        for title in ("Режим", "DIRECT", "PROXY", "VPN")
    )


def routing_rows(
    routing: Any,
    *,
    vpn_enabled: bool = False,
    vpn_is_up: bool = False,
) -> tuple[MonitoringRow, ...]:
    """Describe the routing rules of the active profile."""
    if routing.mode == _PROXY_ALL:
        direct = "активен (bypass local)" if routing.bypass_local_networks else NOT_SET
        return (
            MonitoringRow("Режим", "PROXY_ALL"),
            MonitoringRow("DIRECT", direct),
            MonitoringRow("PROXY", "активен (весь трафик)"),
            MonitoringRow("VPN", NOT_SET),
        )

    direct_count = len(routing.direct_list or [])
    if routing.bypass_local_networks:
        direct_count += 1
    direct = f"активен ({direct_count} правил)" if direct_count else NOT_SET

    proxy_count = len(routing.proxy_list or [])
    proxy = (
        f"активен ({proxy_count} правил + default)" if proxy_count else "активен (default)"
    )

    vpn_count = len(routing.vpn_list or [])
    if vpn_count == 0:
        vpn = NOT_SET
    elif vpn_is_up:
        vpn = f"активен ({vpn_count} правил)"
    elif vpn_enabled:
        vpn = f"правила есть ({vpn_count}), VPN не активен"
    else:
        vpn = f"правила есть ({vpn_count}), VPN выключен"

    return (
        MonitoringRow("Режим", "CUSTOM"),
        MonitoringRow("DIRECT", direct),
        MonitoringRow("PROXY", proxy),
        MonitoringRow("VPN", vpn),
    )


def _connection_rows(
    status: Any, *, is_running: bool, vpn_enabled: bool
) -> tuple[MonitoringRow, ...]:
    if not is_running:
        proxy = MonitoringRow("Прокси", "Не запущен", CLASS_DIM)
    elif status.proxy_ok:
        proxy = MonitoringRow("Прокси", "Работает", CLASS_OK)
    else:
        proxy = MonitoringRow("Прокси", status.proxy_error or "Недоступен", CLASS_ERROR)

    # `vpn_ok` остаётся True и когда монитор вовсе не проверял VPN
    # (src/core/monitor.py: проверка пропускается без имени подключения), поэтому
    # без явного признака настроенности строка сообщала бы «Активен» о
    # выключенном VPN.
    if not vpn_enabled:
        vpn = MonitoringRow("VPN", NOT_CONFIGURED, CLASS_DIM)
    elif not status.vpn_ok:
        vpn = MonitoringRow("VPN", status.vpn_error or "Недоступен", CLASS_ERROR)
    elif is_running:
        vpn = MonitoringRow("VPN", "Активен", CLASS_OK)
    else:
        vpn = MonitoringRow("VPN", UNKNOWN, CLASS_DIM)

    return (proxy, vpn)


def monitoring_view(
    status: Any,
    routing: Any,
    *,
    is_running: bool,
    profile_found: bool = True,
    vpn_enabled: bool = False,
    vpn_is_up: bool = False,
) -> MonitoringView:
    """Build the whole monitoring summary."""
    if not is_running:
        routing_part = _blank_routing()
    elif not profile_found:
        routing_part = (
            MonitoringRow("Режим", "Профиль не найден", CLASS_ERROR),
            MonitoringRow("DIRECT", UNKNOWN, CLASS_DIM),
            MonitoringRow("PROXY", UNKNOWN, CLASS_DIM),
            MonitoringRow("VPN", UNKNOWN, CLASS_DIM),
        )
    else:
        routing_part = routing_rows(routing, vpn_enabled=vpn_enabled, vpn_is_up=vpn_is_up)

    return MonitoringView(
        connection=_connection_rows(status, is_running=is_running, vpn_enabled=vpn_enabled),
        routing=routing_part,
        last_check=format_last_check(status.last_check_time),
    )
