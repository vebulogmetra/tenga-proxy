"""Decode Android-compatible application imports without performing any action."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from urllib.parse import unquote, unquote_plus, urlsplit

from src.db.config import RoutingMode, RoutingSettings
from src.sub.url_policy import validate_url
from src.ui.logic.forms import parse_host_list


@dataclass(frozen=True, repr=False)
class AppLink:
    operation: str
    url: str = ""
    name: str = ""
    routing: RoutingSettings | None = None
    warnings: tuple[str, ...] = ()


def _decode(value: str, *, name=False):
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValueError("Некорректное кодирование ссылки")
    return (unquote_plus if name else unquote)(value, encoding="utf-8", errors="strict")


def parse_app_link(raw: str, *, exceptions=()) -> AppLink:
    if len(raw) > 350000 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("Некорректная или слишком длинная ссылка")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("veblock", "wingeon", "happ"):
        raise ValueError("Неподдерживаемая схема приложения")
    if parts.netloc.lower() == "connect":
        return AppLink("unsupported")
    if parts.query:
        raise ValueError("Неожиданные параметры ссылки")
    if parts.netloc.lower() == "add" and parts.scheme.lower() != "happ":
        url = _decode(parts.path.removeprefix("/"))
        validate_url(url, exceptions=exceptions)
        name = _decode(parts.fragment, name=True)
        name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)[:64]
        return AppLink("subscription", url=url, name=name)
    if parts.netloc.lower() != "routing" or not parts.path.lower().startswith(("/add/", "/onadd/")):
        raise ValueError("Неподдерживаемая операция ссылки")
    encoded = _decode(parts.path.split("/", 2)[2])
    try:
        data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        root = json.loads(data)
    except (binascii.Error, ValueError, UnicodeError, RecursionError):
        raise ValueError("Некорректный профиль маршрутизации") from None
    if not isinstance(root, dict):
        raise ValueError("Ожидается объект маршрутизации")
    fields = {key.lower(): value for key, value in root.items()}
    if len(fields) != len(root):
        raise ValueError("Повторяющиеся поля маршрутизации")
    routing = RoutingSettings()
    global_proxy = fields.get("globalproxy", True)
    if isinstance(global_proxy, str):
        if global_proxy.lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise ValueError("Некорректный режим маршрутизации")
        global_proxy = global_proxy.lower() in ("true", "1", "yes")
    if type(global_proxy) is not bool:
        raise ValueError("Некорректный режим маршрутизации")
    # Happ GlobalProxy describes the catch-all, not whether explicit lists
    # should be discarded. Desktop CUSTOM also keeps the proxy as catch-all.
    routing.mode = RoutingMode.CUSTOM
    warnings = (
        ()
        if global_proxy
        else (
            "Режим «только выбранное через прокси» не поддерживается: вне списков трафик останется через прокси.",
        )
    )
    for destination in ("direct", "proxy", "block"):
        entries = []
        for suffix in ("sites", "ip"):
            values = fields.get(destination + suffix, [])
            if isinstance(values, str):
                values = values.splitlines() if "\n" in values else values.split(",")
            if (
                not isinstance(values, list)
                or len(values) > 5000
                or any(not isinstance(v, str) for v in values)
            ):
                raise ValueError("Некорректный список маршрутизации")
            for value in values:
                entries.extend(parse_host_list(value))
        setattr(routing, destination + "_list", list(dict.fromkeys(entries)))
    return AppLink("routing", routing=routing, warnings=warnings)
