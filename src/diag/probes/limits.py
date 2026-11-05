"""Лимиты и таймауты проб: порт констант PublicMediaProbe.kt и DiagnosticTimeouts.kt."""

from __future__ import annotations

from src.diag.models import ProbeRoute

TELEGRAM_PAGE_BYTES = 65_536
YOUTUBE_PAGE_BYTES = 1_048_576
MEDIA_BYTES = 16_384
DNS_MESSAGE_BYTES = 16_384
DNS_TRANSPORT_BYTES = 4_096
HEADER_BYTES = 16_384

SYSTEM_DNS_TIMEOUT_S = 5.0
DOH_TIMEOUT_S = 5.0
DNS_TRANSPORT_TIMEOUT_S = 3.0
CONNECTION_TIMEOUT_S = 5.0


def http_timeout_s(route: ProbeRoute) -> float:
    """Запрос через прокси включает CONNECT и весь удалённый путь, а не только локальный сокет."""
    return 15.0 if route is ProbeRoute.ACTIVE_TUNNEL else 5.0


def media_request_timeout_s(route: ProbeRoute) -> float:
    return 15.0 if route is ProbeRoute.ACTIVE_TUNNEL else 7.0


def media_total_timeout_s(route: ProbeRoute) -> float:
    return 30.0 if route is ProbeRoute.ACTIVE_TUNNEL else 15.0
