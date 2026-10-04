"""Проверка обновлений ядра xray: только сообщить, ничего не скачивать.

Бинарник приложение не трогает: в AppImage он лежит внутри образа, а в
dev-режиме его ставит `cli.py setup-dev`. Здесь — сравнение установленной
версии с закреплённой и с релизами на GitHub.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from src.db.data_store import DataStore

# Версия, под которую написана сборка конфига. Она же закреплена в
# core/scripts/install_dev.sh (XRAY_VERSION) — тест следит, чтобы они совпадали.
PINNED_CORE_VERSION = "26.9.9"

# `/releases/latest` отдаёт только стабильные релизы, а закреплённая версия —
# пререлиз, поэтому нужен список.
RELEASES_URL = "https://api.github.com/repos/XTLS/Xray-core/releases?per_page=30"
REQUEST_TIMEOUT_SECONDS = 10
CHECK_INTERVAL_SECONDS = 3 * 24 * 60 * 60

UNKNOWN = "unknown"
CURRENT = "current"
AVAILABLE = "available"
BEHIND_PINNED = "behind_pinned"

Version = tuple[int, ...]
_VERSION = re.compile(r"\d+(?:\.\d+)+")


def parse_version(text: str) -> Version | None:
    """Версия из тега (`v26.9.9`) или из вывода `xray version`."""
    match = _VERSION.search(text or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


@dataclass(frozen=True)
class KnownReleases:
    """Что известно о релизах: новейший стабильный и новейший пререлиз."""

    stable: str = ""
    prerelease: str = ""


@dataclass(frozen=True)
class CoreUpdateStatus:
    """Итог сравнения: `kind` и версия, о которой идёт речь."""

    kind: str
    installed: str
    target: str = ""


def newest_releases(payload: Any) -> KnownReleases:
    """Выбрать новейшие версии из ответа GitHub. Черновики и мусор пропускаются."""
    newest: dict[bool, tuple[Version, str]] = {}
    for release in payload if isinstance(payload, list) else []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        version = parse_version(str(release.get("tag_name") or ""))
        if version is None:
            continue
        is_prerelease = bool(release.get("prerelease"))
        text = ".".join(str(part) for part in version)
        if is_prerelease not in newest or version > newest[is_prerelease][0]:
            newest[is_prerelease] = (version, text)

    return KnownReleases(
        stable=newest[False][1] if False in newest else "",
        prerelease=newest[True][1] if True in newest else "",
    )


def fetch_releases(get: Callable[..., Any] = requests.get) -> KnownReleases:
    """Спросить GitHub о релизах. В запросе нет ничего о пользователе и установке."""
    response = get(
        RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "tenga-proxy"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return newest_releases(response.json())


def evaluate(
    installed: str, known: KnownReleases, pinned: str = PINNED_CORE_VERSION
) -> CoreUpdateStatus:
    """Сравнить установленное ядро с закреплённой версией и с релизами."""
    installed_version = parse_version(installed)
    if installed_version is None:
        return CoreUpdateStatus(UNKNOWN, installed)

    pinned_version = parse_version(pinned)
    if pinned_version is not None and installed_version < pinned_version:
        return CoreUpdateStatus(BEHIND_PINNED, installed, pinned)

    stable_version = parse_version(known.stable)
    prerelease_version = parse_version(known.prerelease)

    offers: list[tuple[Version, str]] = []
    if stable_version is not None:
        offers.append((stable_version, known.stable))
    # Пререлиз предлагается только тому, у кого уже стоит пререлиз, то есть
    # версия новее последнего стабильного релиза.
    runs_prerelease = stable_version is None or installed_version > stable_version
    if prerelease_version is not None and runs_prerelease:
        offers.append((prerelease_version, known.prerelease))

    if not offers:
        return CoreUpdateStatus(UNKNOWN, installed)

    newest_version, newest = max(offers)
    if newest_version > installed_version:
        return CoreUpdateStatus(AVAILABLE, installed, newest)
    return CoreUpdateStatus(CURRENT, installed)


def known_releases(config: DataStore) -> KnownReleases:
    """Релизы, запомненные с прошлой проверки."""
    return KnownReleases(
        stable=config.core_update_stable,
        prerelease=config.core_update_prerelease,
    )


def is_check_due(config: DataStore, now: float) -> bool:
    """Пора ли спросить GitHub снова."""
    return now - config.core_update_checked_at >= CHECK_INTERVAL_SECONDS


def refresh_known_releases(
    config: DataStore,
    *,
    now: float,
    fetch: Callable[[], KnownReleases] = fetch_releases,
) -> KnownReleases:
    """Обновить запомненные релизы. Сетевой вызов: только из фонового потока.

    Ошибка сети уходит наверх, а пустой ответ (например, исчерпан лимит API)
    прежних сведений не стирает; в обоих случаях проверка остаётся «не сделанной».
    """
    fetched = fetch()
    if not fetched.stable and not fetched.prerelease:
        return known_releases(config)

    config.core_update_stable = fetched.stable
    config.core_update_prerelease = fetched.prerelease
    config.core_update_checked_at = int(now)
    return fetched
