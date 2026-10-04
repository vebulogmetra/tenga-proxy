"""Метаданные подписки: заголовки ответа и строки ``#key: value`` в теле.

Берём только косметику и ссылки. Ключи, которыми провайдер управлял бы
настройками клиента (``hide-settings``, ``routing``, mux, per-app), сознательно
не распознаются.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from src.fmt.parsers import decode_base64

if TYPE_CHECKING:
    from src.db.profiles import ProfileGroup

KEY_USERINFO = "subscription-userinfo"
KEY_UPDATE_INTERVAL = "profile-update-interval"
KEY_ANNOUNCE = "announce"
KEY_SUPPORT_URL = "support-url"
KEY_PROFILE_TITLE = "profile-title"
KEY_WEB_PAGE_URL = "profile-web-page-url"

KNOWN_KEYS = frozenset(
    {
        KEY_USERINFO,
        KEY_UPDATE_INTERVAL,
        KEY_ANNOUNCE,
        KEY_SUPPORT_URL,
        KEY_PROFILE_TITLE,
        KEY_WEB_PAGE_URL,
    }
)

MAX_TITLE_LENGTH = 64

_BASE64_PREFIX = "base64:"
_BODY_LINE = re.compile(r"^#\s*([A-Za-z0-9-]+)\s*:\s*(.*)$")
_BASE64_PAYLOAD = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# В декодированном тексте допустимы только перевод строки и табуляция: прочие
# управляющие символы означают, что декодировали не base64, а обычное слово.
_BINARY_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_USERINFO_FIELDS = ("upload", "download", "total", "expire")
_SUPPORT_SCHEMES = ("http", "https", "tg")


@dataclass(frozen=True)
class SubscriptionUserInfo:
    """Трафик и срок из ``subscription-userinfo``: байты и unix-время."""

    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0

    @classmethod
    def from_header(cls, header: str | None) -> SubscriptionUserInfo | None:
        """Parse ``upload=N; download=N; total=N; expire=N``; None when nothing is known."""
        values: dict[str, int] = {}
        for part in (header or "").split(";"):
            key, separator, value = part.partition("=")
            key = key.strip().lower()
            if not separator or key not in _USERINFO_FIELDS:
                continue
            try:
                values[key] = max(int(value.strip()), 0)
            except ValueError:
                values[key] = 0
        return cls(**values) if values else None

    def to_header(self) -> str:
        return "; ".join(f"{name}={getattr(self, name)}" for name in _USERINFO_FIELDS)

    @property
    def used(self) -> int:
        return self.upload + self.download

    @property
    def is_unlimited(self) -> bool:
        return self.total == 0


@dataclass(frozen=True)
class SubscriptionMetadata:
    """Всё, что провайдер сообщил о подписке помимо списка серверов."""

    user_info: SubscriptionUserInfo | None = None
    update_interval_hours: int = 0  # только для показа: фонового обновления нет
    announce: str = ""
    support_url: str = ""
    title: str = ""
    web_page_url: str = ""

    def overridden_by(self, body: SubscriptionMetadata) -> SubscriptionMetadata:
        """Values from the body win over headers; empty ones do not erase anything."""
        merged = {f.name: getattr(body, f.name) or getattr(self, f.name) for f in fields(self)}
        return SubscriptionMetadata(**merged)


def decode_value(raw: str, lenient_base64: bool = False) -> str:
    """Decode a ``base64:`` value; with ``lenient_base64`` the prefix is optional.

    Нестрогий режим нужен только для ``announce``: он исторически приходит в
    base64 без префикса. Обычный текст при этом должен остаться собой, поэтому
    результат принимается, только если это корректный UTF-8 без управляющих
    символов.
    """
    has_prefix = raw[: len(_BASE64_PREFIX)].lower() == _BASE64_PREFIX
    if not has_prefix and not lenient_base64:
        return raw

    payload = (raw[len(_BASE64_PREFIX) :] if has_prefix else raw).strip()
    if not _BASE64_PAYLOAD.match(payload):
        return raw

    payload = payload.rstrip("=")
    payload += "=" * (-len(payload) % 4)
    try:
        if "+" in payload or "/" in payload:
            decoded = base64.b64decode(payload, validate=True)
        else:
            decoded = base64.urlsafe_b64decode(payload)
        text = decoded.decode("utf-8")
    except (binascii.Error, ValueError):
        return raw

    if not text or _BINARY_CHARS.search(text):
        return raw
    return text


def _sanitize_title(raw: str) -> str:
    return _CONTROL_CHARS.sub("", raw).strip()[:MAX_TITLE_LENGTH]


def _parse_interval(raw: str) -> int:
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def parse_metadata(values: Mapping[str, str]) -> SubscriptionMetadata:
    """Build metadata from ``lower-case key -> raw value`` pairs."""

    def text(key: str) -> str:
        raw = values.get(key)
        if not isinstance(raw, str):
            return ""
        return decode_value(raw.strip(), lenient_base64=key == KEY_ANNOUNCE).strip()

    return SubscriptionMetadata(
        user_info=SubscriptionUserInfo.from_header(text(KEY_USERINFO)),
        update_interval_hours=_parse_interval(text(KEY_UPDATE_INTERVAL)),
        announce=text(KEY_ANNOUNCE),
        support_url=text(KEY_SUPPORT_URL),
        title=_sanitize_title(text(KEY_PROFILE_TITLE)),
        web_page_url=text(KEY_WEB_PAGE_URL),
    )


def parse_body_line(line: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` for a ``#key: value`` line with a known key."""
    match = _BODY_LINE.match(line.strip())
    if match is None:
        return None
    key = match.group(1).lower()
    if key not in KNOWN_KEYS:
        return None
    return key, match.group(2).strip()


def metadata_from_headers(headers: Mapping[str, str] | None) -> SubscriptionMetadata:
    """Read metadata from response headers (names are case-insensitive)."""
    values: dict[str, str] = {}
    try:
        items = list((headers or {}).items())
    except (AttributeError, TypeError):
        # Ответ без настоящих заголовков (заглушка в тестах).
        items = []
    for name, value in items:
        key = str(name).lower()
        if key in KNOWN_KEYS and isinstance(value, str):
            values[key] = value
    return parse_metadata(values)


def metadata_from_body(content: str) -> SubscriptionMetadata:
    """Read ``#key: value`` lines, looking inside a base64 body as well."""
    text = decode_base64(content.strip()) or content
    values: dict[str, str] = {}
    for line in text.split("\n"):
        parsed = parse_body_line(line)
        if parsed is not None:
            values.setdefault(*parsed)
    return parse_metadata(values)


def read_metadata(headers: Mapping[str, str] | None, content: str) -> SubscriptionMetadata:
    """Headers overridden by the body: the body is what the provider fully controls."""
    return metadata_from_headers(headers).overridden_by(metadata_from_body(content))


def default_subscription_name(url: str) -> str:
    """Имя подписки по умолчанию — хост адреса.

    По нему же отличаем «имя никто не задавал» от имени, выбранного
    пользователем: ``profile-title`` переименовывает только первое.
    """
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        host = None
    return host or url.strip()


def _scheme_and_host(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url.strip())
        return parts.scheme.lower(), parts.hostname or ""
    except ValueError:
        return "", ""


def is_safe_web_page_url(url: str) -> bool:
    """Страница продления открывается в браузере: только https с хостом."""
    scheme, host = _scheme_and_host(url)
    return scheme == "https" and bool(host)


def is_safe_support_url(url: str) -> bool:
    """Ссылка поддержки: сайт или Telegram, но не ``javascript:`` и не ``file:``."""
    scheme, _host = _scheme_and_host(url)
    return scheme in _SUPPORT_SCHEMES


def apply_metadata(group: ProfileGroup, metadata: SubscriptionMetadata) -> None:
    """Store provider metadata on the subscription group.

    Пустое значение не стирает сохранённое: нестандартные заголовки режет CDN,
    и один ответ без них не должен обнулять остаток трафика. Исключение —
    объявление: это сообщение «на сейчас», вчерашнее показывать незачем.
    """
    if metadata.user_info is not None:
        group.sub_user_info = metadata.user_info.to_header()
    if metadata.update_interval_hours > 0:
        group.sub_update_interval = metadata.update_interval_hours
    group.sub_announce = metadata.announce
    # Ссылки фильтруются и здесь, и при показе: в файле профилей не должно
    # лежать то, что приложение не откроет.
    if is_safe_support_url(metadata.support_url):
        group.sub_support_url = metadata.support_url.strip()
    if is_safe_web_page_url(metadata.web_page_url):
        group.sub_web_page_url = metadata.web_page_url.strip()

    title = metadata.title
    if title and group.name == default_subscription_name(group.subscription_url):
        group.name = title
