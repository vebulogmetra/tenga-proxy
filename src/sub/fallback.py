"""Разовая загрузка подписки с запасного адреса провайдера.

Постоянно адрес подписки меняется только с подтверждения пользователя
(src/sub/url_change.py). Разовая загрузка его не меняет: следующее обновление
снова начинается с основного адреса.
"""

from __future__ import annotations

import requests

from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.url_change import is_acceptable_subscription_url, same_subscription_url

_TOKEN_REVOKED = (404, 410)


class FallbackExhaustedError(Exception):
    """Не сработали оба адреса; показывать нужно ``display_error``."""

    def __init__(self, display_error: BaseException) -> None:
        # Не str(display_error): в тексте ошибок requests лежит адрес с токеном.
        super().__init__("Не сработали основной и запасной адреса подписки")
        self.display_error = display_error


def is_worth_trying(error: BaseException) -> bool:
    """Whether the failure of the primary address justifies the fallback.

    403 и 429 может отвечать сам CDN. 404 и 410 означают отозванный токен:
    запасной адрес несёт тот же токен. Прочие коды — ответ сервера, а не сбой
    доступа к нему.
    """
    if isinstance(error, SubscriptionTooLargeError):
        return False
    if isinstance(error, SubscriptionHttpError):
        return 500 <= error.status_code <= 599 or error.is_access_denied
    return isinstance(error, requests.RequestException)


def usable_url(primary_url: str, stored: str | None) -> str | None:
    """The fallback address to request, or None.

    Проверяется при каждой загрузке: файлу профилей не доверяем. Панель отдаёт
    второй адрес всегда, поэтому после перехода на него он равен основному.
    """
    url = (stored or "").strip()
    if not is_acceptable_subscription_url(url) or same_subscription_url(url, primary_url):
        return None
    return url


def display_error(primary: BaseException, fallback: BaseException) -> BaseException:
    """Pick the error to show: a server's answer explains more than a lost connection."""
    if not isinstance(primary, SubscriptionHttpError) and isinstance(
        fallback, SubscriptionHttpError
    ):
        return fallback
    return primary


def can_propose_after(error: BaseException) -> bool:
    """Whether a permanent address change still makes sense after this failure."""
    if isinstance(error, FallbackExhaustedError):
        return False
    return not (isinstance(error, SubscriptionHttpError) and error.status_code in _TOKEN_REVOKED)
