"""Данные устройства в запросе подписки.

Часть провайдеров считает лимит устройств по ``x-hwid`` и без него отвечает
403. HWID — стабильный идентификатор, поэтому уходит только по явному флагу
пользователя; при выключенном флаге он даже не создаётся.
"""

from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.data_store import DataStore

HEADER_HWID = "x-hwid"
HEADER_DEVICE_OS = "x-device-os"
HEADER_OS_VERSION = "x-ver-os"
HEADER_DEVICE_MODEL = "x-device-model"
HEADER_LANGUAGE = "Accept-Language"

OS_NAME = "Linux"
UNKNOWN_MODEL = "PC"

_DMI_PRODUCT_NAME = Path("/sys/class/dmi/id/product_name")
# Язык системы, а не интерфейса: LC_MESSAGES приложение подменяет само
# (src/ui/logic/locale.py).
_LANGUAGE_VARS = ("LC_ALL", "LANG")


@dataclass(frozen=True)
class DeviceInfo:
    """Что сообщается провайдеру об устройстве помимо HWID."""

    os_version: str
    model: str
    language: str


def ascii_header_value(raw: str) -> str:
    """Оставить печатный ASCII: остальное requests в заголовок не пропустит."""
    return "".join(ch for ch in raw if " " <= ch <= "~").strip()


def _os_version() -> str:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return platform.release()
    name = release.get("NAME", "").strip()
    version = release.get("VERSION_ID", "").strip()
    return f"{name} {version}".strip() or platform.release()


def _model() -> str:
    try:
        return _DMI_PRODUCT_NAME.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _language() -> str:
    for name in _LANGUAGE_VARS:
        # "ru_RU.UTF-8" -> "ru-RU"; "C" и "POSIX" языком не являются.
        value = os.environ.get(name, "").split(".")[0].split("@")[0]
        if value and value not in ("C", "POSIX"):
            return value.replace("_", "-")
    return ""


def read_device_info() -> DeviceInfo:
    """Collect the device description from the running system."""
    return DeviceInfo(
        os_version=_os_version(),
        model=_model() or UNKNOWN_MODEL,
        language=_language(),
    )


def ensure_hwid(config: DataStore) -> str:
    """Return the stored HWID, creating it on first use.

    Вызывается там, где настройки затем сохраняются на диск (диалог настроек):
    несохранённый идентификатор менялся бы при каждом запуске, и провайдер
    считал бы каждый запуск новым устройством.
    """
    if not config.sub_hwid:
        config.sub_hwid = str(uuid.uuid4())
    return config.sub_hwid


def device_headers(config: DataStore, info: DeviceInfo | None = None) -> dict[str, str]:
    """Headers describing the device; empty unless the user opted in."""
    if not config.sub_send_device_info or not config.sub_hwid:
        return {}

    info = info or read_device_info()
    headers = {
        HEADER_HWID: config.sub_hwid,
        HEADER_DEVICE_OS: OS_NAME,
        HEADER_OS_VERSION: info.os_version,
        HEADER_DEVICE_MODEL: info.model,
        HEADER_LANGUAGE: info.language,
    }
    cleaned = {name: ascii_header_value(value) for name, value in headers.items()}
    return {name: value for name, value in cleaned.items() if value}
