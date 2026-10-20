"""Смена адреса подписки по подсказке провайдера.

Адрес меняется только после подтверждения пользователя: автозамена отдала бы
серверу подписки право молча перенаправить клиента куда угодно.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def is_acceptable_subscription_url(url: str) -> bool:
    """Only public HTTPS destinations may be proposed by a provider."""
    from src.sub.url_policy import SubscriptionPolicyError, validate_url

    if not url or len(url) > MAX_URL_LENGTH:
        return False
    try:
        validate_url(url)
    except SubscriptionPolicyError:
        return False
    return True


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
