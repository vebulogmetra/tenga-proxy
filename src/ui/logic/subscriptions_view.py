"""Subscription list logic (GTK-free)."""

from __future__ import annotations

import datetime
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.ui.logic.formatting import format_bytes

NEVER_UPDATED = "Никогда"
_TIME_FORMAT = "%d.%m.%Y %H:%M"
_DATE_FORMAT = "%d.%m.%Y"


@dataclass(frozen=True)
class SubscriptionRow:
    """One subscription as shown in the list."""

    group_id: int
    name: str
    url: str
    updated_text: str
    profile_count: int
    # Метаданные провайдера; пустые строки — провайдер их не сообщил.
    usage_text: str = ""
    expire_text: str = ""
    expired: bool = False
    announce: str = ""
    support_url: str = ""
    web_page_url: str = ""

    @property
    def details_text(self) -> str:
        """Usage and expiry on one line."""
        return " · ".join(part for part in (self.usage_text, self.expire_text) if part)


def format_updated(timestamp: int) -> str:
    """Render the last update time, including the "never" case."""
    if not timestamp:
        return NEVER_UPDATED
    return datetime.datetime.fromtimestamp(timestamp).strftime(_TIME_FORMAT)


def format_usage(used: int, total: int) -> str:
    """Render the traffic counter; an unknown one renders as nothing."""
    if total > 0:
        return f"{format_bytes(used)} из {format_bytes(total)}"
    if used > 0:
        return f"{format_bytes(used)}, без лимита"
    return ""


def format_expire(expire: int, now: int) -> tuple[str, bool]:
    """Render the expiry date and tell whether it has passed. Zero means "never"."""
    if expire <= 0:
        return "", False
    date = datetime.datetime.fromtimestamp(expire).strftime(_DATE_FORMAT)
    if expire < now:
        return f"истекла {date}", True
    return f"до {date}", False


def build_subscription_rows(
    groups: Mapping[int, Any],
    profile_counts: Mapping[int, int],
    *,
    query: str = "",
    now: int | None = None,
) -> list[SubscriptionRow]:
    """Build the subscription list for the given filter.

    URL сохраняется целиком: обрезку делает виджет, а фильтр должен искать по
    полному адресу, иначе часть подписок стала бы ненаходимой.
    """
    # Импорт внутри функции: `src.sub` тянет requests, а модуль нужен при
    # каждом открытии окна.
    from src.sub.metadata import SubscriptionUserInfo, is_safe_support_url, is_safe_web_page_url

    normalized = query.strip().lower()
    current_time = int(time.time()) if now is None else now

    rows: list[SubscriptionRow] = []
    for group in groups.values():
        if not group.is_subscription:
            continue

        url = group.subscription_url or ""
        updated_text = format_updated(group.last_updated)

        if normalized and not (
            normalized in (group.name or "").lower()
            or normalized in url.lower()
            or normalized in updated_text.lower()
        ):
            continue

        info = SubscriptionUserInfo.from_header(group.sub_user_info)
        usage_text = format_usage(info.used, info.total) if info else ""
        expire_text, expired = format_expire(info.expire, current_time) if info else ("", False)
        support_url = group.sub_support_url
        web_page_url = group.sub_web_page_url

        rows.append(
            SubscriptionRow(
                group_id=group.id,
                name=group.name,
                url=url,
                updated_text=updated_text,
                profile_count=profile_counts.get(group.id, 0),
                usage_text=usage_text,
                expire_text=expire_text,
                expired=expired,
                announce=group.sub_announce,
                support_url=support_url if is_safe_support_url(support_url) else "",
                web_page_url=web_page_url if is_safe_web_page_url(web_page_url) else "",
            )
        )

    return rows


DEVICE_INFO_HINT = "Возможно, провайдеру нужны данные устройства: Настройки → Подписки."


def describe_update_error(error: BaseException, *, device_info_sent: bool = True) -> str:
    """Explain a failed update without quoting the subscription address.

    Текст ошибок requests содержит полный URL, а в нём — токен подписки:
    сообщение уходит в уведомление и в журнал, поэтому собирается заново.
    """
    # Импорт внутри функции: модуль списка подписок не должен тянуть requests
    # при каждом открытии окна.
    import requests

    from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError

    if isinstance(error, SubscriptionHttpError):
        text = f"сервер ответил {error.status_code}"
        if error.is_access_denied and error.body_snippet:
            text += f": {error.body_snippet}"
        if error.is_access_denied and not device_info_sent:
            text = f"{text.rstrip('.')}. {DEVICE_INFO_HINT}"
        return text
    if isinstance(error, SubscriptionTooLargeError):
        return "ответ сервера больше 10 МБ"
    if isinstance(error, requests.Timeout):
        return "сервер подписки не ответил вовремя"
    if isinstance(error, requests.ConnectionError):
        return "нет связи с сервером подписки"
    return str(error)
