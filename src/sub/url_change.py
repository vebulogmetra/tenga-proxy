"""Смена адреса подписки по подсказке провайдера.

Адрес меняется только после подтверждения пользователя: автозамена отдала бы
серверу подписки право молча перенаправить клиента куда угодно.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

REASON_NEW_URL = "new-url"  # провайдер сообщил новый адрес при удачном обновлении
REASON_FALLBACK_URL = "fallback-url"  # обновление не удалось, есть запасной адрес

MAX_URL_LENGTH = 2048

_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal")


@dataclass(frozen=True)
class UrlChangeProposal:
    """Предложение, которое пользователь подтверждает или отклоняет."""

    group_id: int
    new_url: str
    reason: str


def _is_local_host(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        # inet_aton разбирает сокращённый, числовой и hex IPv4 без DNS-запроса.
        try:
            address = ipaddress.ip_address(socket.inet_aton(lowered))
        except OSError:
            return False
    return not address.is_global


def is_acceptable_subscription_url(url: str) -> bool:
    """Годится ли адрес как адрес подписки: http(s) с публичным хостом."""
    if not url or len(url) > MAX_URL_LENGTH or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        # hostname не проверяет порт; чтение port отклоняет неверный диапазон/текст.
        _ = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https") or not host:
        return False
    return not _is_local_host(host)


def propose_url_change(
    group_id: int, current_url: str, candidate: str | None, reason: str
) -> UrlChangeProposal | None:
    """Build a proposal, or None when there is nothing safe and new to offer."""
    url = (candidate or "").strip()
    if not url or url == current_url.strip():
        return None
    if not is_acceptable_subscription_url(url):
        return None
    return UrlChangeProposal(group_id=group_id, new_url=url, reason=reason)
