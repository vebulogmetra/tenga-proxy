"""Validation shared by the dialogs (GTK-free).

Каждая форма проверяется здесь, а не в виджете: правила одни и те же для
диалога добавления, редактирования и вставки из буфера, а без GTK их можно
прогонять в обычных тестах.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EMPTY_LINK = "Введите ссылку подключения"
BAD_LINK = "Не удалось разобрать ссылку"
EMPTY_GROUP_NAME = "Введите название группы"
EMPTY_SUBSCRIPTION_NAME = "Введите название подписки"
EMPTY_SUBSCRIPTION_URL = "Введите URL подписки"
BAD_SUBSCRIPTION_URL = "URL должен начинаться с http:// или https://"

_HTTP_PREFIXES = ("http://", "https://")
_SEPARATORS = (",", ";")


@dataclass(frozen=True)
class FormResult:
    """Outcome of validating one form."""

    ok: bool
    message: str = ""
    value: Any = None
    bean: Any = None


def validate_profile_link(link: str, *, name: str = "") -> FormResult:
    """Parse a share link and apply an optional custom name."""
    # Импорт внутри функции: `src.fmt` тянет разбор всех протоколов, а модуль
    # должен оставаться дешёвым для форм, которым разбор не нужен.
    from src.fmt import parse_link

    text = (link or "").strip()
    if not text:
        return FormResult(False, EMPTY_LINK)

    bean = parse_link(text)
    if bean is None:
        return FormResult(False, BAD_LINK)

    custom = (name or "").strip()
    if custom:
        bean.name = custom

    return FormResult(True, f"{bean.proxy_type.upper()}: {bean.display_address}", bean=bean)


def validate_subscription(name: str, url: str) -> FormResult:
    """Check the name and address of a subscription."""
    clean_name = (name or "").strip()
    clean_url = (url or "").strip()

    if not clean_name:
        return FormResult(False, EMPTY_SUBSCRIPTION_NAME)
    if not clean_url:
        return FormResult(False, EMPTY_SUBSCRIPTION_URL)
    if not clean_url.startswith(_HTTP_PREFIXES):
        return FormResult(False, BAD_SUBSCRIPTION_URL)

    return FormResult(True, value=(clean_name, clean_url))


def validate_group_name(name: str) -> FormResult:
    """Check a group name."""
    clean = (name or "").strip()
    if not clean:
        return FormResult(False, EMPTY_GROUP_NAME)
    return FormResult(True, value=clean)


def parse_host_list(text: str | None) -> list[str]:
    """Turn a routing text area into a list of hosts.

    Порядок ввода сохраняется: правила маршрутизации применяются сверху вниз,
    и сортировка молча изменила бы поведение профиля.
    """
    if not text:
        return []

    for separator in _SEPARATORS:
        text = text.replace(separator, "\n")

    result: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        item = line.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
