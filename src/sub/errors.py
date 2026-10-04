"""Ошибки загрузки подписки."""

from __future__ import annotations

import re
from typing import Any

import requests

MAX_RESPONSE_SIZE = 10 * 1024 * 1024
MAX_SNIPPET = 200

_ACCESS_DENIED = (403, 429)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"\s+")


def snippet_of(raw_body: Any) -> str:
    """Начало тела ответа, пригодное для показа в одной строке.

    Провайдеры объясняют отказ в теле («превышен лимит устройств»): это
    полезнее голого кода. HTML-страницы CDN ничего не объясняют и отбрасываются.
    """
    if not isinstance(raw_body, str):
        return ""
    text = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub("", raw_body)).strip()
    if text.startswith("<"):
        return ""
    return text[:MAX_SNIPPET]


class SubscriptionHttpError(requests.HTTPError):
    """Окончательный HTTP-ответ провайдера: не повторяется.

    Текст ошибки не содержит адреса подписки — в нём токен пользователя, а
    сообщение уходит в уведомление и в журнал.
    """

    def __init__(self, status_code: int, body_snippet: str = "", **kwargs: Any) -> None:
        self.status_code = status_code
        self.body_snippet = body_snippet
        super().__init__(self._message(), **kwargs)

    @property
    def is_access_denied(self) -> bool:
        return self.status_code in _ACCESS_DENIED

    def _message(self) -> str:
        if self.is_access_denied and self.body_snippet:
            return f"HTTP {self.status_code}: {self.body_snippet}"
        return f"HTTP {self.status_code}"


class SubscriptionTooLargeError(requests.RequestException):
    """Ответ больше MAX_RESPONSE_SIZE: окончательный, повтор вернёт то же самое."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__(f"Ответ сервера слишком большой: {size} символов")
