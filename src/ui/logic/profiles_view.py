"""Filtering and sorting for the profile tree (GTK-free).

Страница получает готовые `GroupRow`/`ProfileRow` и только раскладывает их по
виджетам, поэтому правила отбора проверяются обычным pytest без дисплея.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

SUBSCRIPTION_ICON = "network-server-symbolic"
GROUP_ICON = "folder-symbolic"

UNKNOWN_PING = "—"


class SortKey(StrEnum):
    """Column the profile list is ordered by."""

    NAME = "name"
    TYPE = "type"
    PING = "ping"


@dataclass(frozen=True)
class ProfileRow:
    """One profile as shown in the tree."""

    profile_id: int
    title: str
    proxy_type: str
    address: str
    latency_ms: int
    is_active: bool


@dataclass(frozen=True)
class GroupRow:
    """A group with the profiles that survived filtering."""

    group_id: int
    title: str
    icon_name: str
    is_subscription: bool
    children: tuple[ProfileRow, ...]

    @property
    def count(self) -> int:
        return len(self.children)


def ping_text(latency_ms: int) -> str:
    """Render a latency value, including the "not measured" case."""
    if latency_ms is None or latency_ms < 0:
        return UNKNOWN_PING
    return f"{latency_ms} ms"


def _latency_of(profile: Any) -> int:
    latency = getattr(profile, "latency_ms", -1)
    return -1 if latency is None else int(latency)


def _matches(profile: Any, query: str) -> bool:
    """Match the four fields the GTK3 filter searched."""
    address = getattr(getattr(profile, "bean", None), "display_address", "") or ""
    return (
        query in (profile.name or "").lower()
        or query in (getattr(profile, "proxy_type", "") or "").lower()
        or query in address.lower()
    )


def _sorted_profiles(profiles: list[Any], sort_key: SortKey, ascending: bool) -> list[Any]:
    if sort_key is SortKey.TYPE:
        return sorted(
            profiles,
            key=lambda p: (getattr(p, "proxy_type", "") or "").lower(),
            reverse=not ascending,
        )

    if sort_key is SortKey.PING:
        # Непроверенные профили остаются в конце в обоих направлениях: сортировка
        # одним ключом с reverse переставила бы прочерки в начало убывающего
        # порядка, и колонка «Пинг» начиналась бы с пустых значений.
        measured = [p for p in profiles if _latency_of(p) >= 0]
        untested = [p for p in profiles if _latency_of(p) < 0]
        measured.sort(key=_latency_of, reverse=not ascending)
        untested.sort(key=lambda p: (p.name or "").lower())
        return measured + untested

    return sorted(profiles, key=lambda p: (p.name or "").lower(), reverse=not ascending)


def build_profile_rows(
    groups: Mapping[int, Any],
    profiles_by_group: Mapping[int, Iterable[Any]],
    *,
    query: str = "",
    sort_key: SortKey = SortKey.NAME,
    ascending: bool = True,
    active_profile_id: int = -1,
) -> list[GroupRow]:
    """Build the profile tree for the given filter and ordering.

    Правила повторяют GTK3-окно: подписки идут первыми, совпадение запроса с
    именем группы показывает её целиком, а группа без видимых профилей исчезает.
    """
    normalized = query.strip().lower()

    ordered_groups = sorted(
        groups.values(), key=lambda g: (not g.is_subscription, (g.name or "").lower())
    )

    rows: list[GroupRow] = []
    for group in ordered_groups:
        group_profiles = list(profiles_by_group.get(group.id, ()))

        if normalized:
            if normalized in (group.name or "").lower():
                visible = group_profiles
            else:
                visible = [p for p in group_profiles if _matches(p, normalized)]
            if not visible:
                continue
        else:
            # Пустая группа не показывается и без фильтра: хранилище всегда
            # заводит группу «Default», и без этого свежая установка встречала
            # бы пользователя пустой строкой вместо приглашения добавить профиль.
            if not group_profiles:
                continue
            visible = group_profiles

        children = tuple(
            ProfileRow(
                profile_id=profile.id,
                title=profile.name,
                proxy_type=getattr(profile, "proxy_type", "") or "",
                address=getattr(getattr(profile, "bean", None), "display_address", "") or "",
                latency_ms=_latency_of(profile),
                is_active=profile.id == active_profile_id,
            )
            for profile in _sorted_profiles(visible, sort_key, ascending)
        )

        rows.append(
            GroupRow(
                group_id=group.id,
                title=group.name,
                icon_name=SUBSCRIPTION_ICON if group.is_subscription else GROUP_ICON,
                is_subscription=bool(group.is_subscription),
                children=children,
            )
        )

    return rows
