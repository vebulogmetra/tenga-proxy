"""Filtering and sorting for the profile tree (GTK-free).

Страница получает готовые `GroupRow`/`ProfileRow` и только раскладывает их по
виджетам, поэтому правила отбора проверяются обычным pytest без дисплея.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from src.core.probe_result import PROBE_TIMEOUT_SECONDS, ProbeFailure
from src.ui.logic.country_flags import split_flag_prefix

SUBSCRIPTION_ICON = "network-server-symbolic"
GROUP_ICON = "folder-symbolic"

UNKNOWN_PING = "—"

# Отказ при проверке: короткая метка справа в строке и первая строка подсказки.
FAILURE_LABELS = {
    ProbeFailure.TIMEOUT: "нет ответа",
    ProbeFailure.UNREACHABLE: "нет связи",
}
FAILURE_LABEL = "ошибка"
FAILURE_REASONS = {
    ProbeFailure.TIMEOUT: f"Сервер не ответил за {PROBE_TIMEOUT_SECONDS} с",
    ProbeFailure.UNREACHABLE: "Ядро не смогло соединиться с сервером",
    ProbeFailure.BAD_RESPONSE: "Неожиданный ответ при проверке",
    ProbeFailure.INVALID_CONFIG: "Параметры сервера не собираются в конфигурацию",
    ProbeFailure.REJECTED: "Ядро отвергло параметры сервера",
    ProbeFailure.CORE_FAILED: "Не удалось запустить ядро для проверки",
}
CHECKED_PREFIX = "Проверено: "

EMPTY_TITLE = "Серверов пока нет"
EMPTY_DESCRIPTION = "Добавьте сервер по ссылке или подключите подписку."
SEARCH_PLACEHOLDER = "Имя, тип, адрес или группа"
NO_RESULTS_TEXT = "Ничего не найдено. Измените запрос."
SELECTED_NONE = "Сервер не выбран"
SELECTED_PREFIX = "Выбран: "
GROUP_SEPARATOR = "  ·  "


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
    probe_failure: ProbeFailure | None = None
    probe_detail: str = ""
    checked_at: int = 0


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


def ping_is_failure(row: ProfileRow) -> bool:
    """Сервер не прошёл последний замер: метка рисуется цветом ошибки."""
    return row.probe_failure is not None


def ping_text(row: ProfileRow) -> str:
    """Задержка, метка отказа или «—», если проверки не было."""
    if row.probe_failure is not None:
        return FAILURE_LABELS.get(row.probe_failure, FAILURE_LABEL)
    if row.latency_ms is None or row.latency_ms < 0:
        return UNKNOWN_PING
    return f"{row.latency_ms} мс"


def checked_text(checked_at: int, now: float) -> str:
    """Когда был замер: «только что», «5 мин назад», «3 ч назад» или дата."""
    age = int(now) - int(checked_at)
    if age < 60:
        return "только что"
    if age < 3600:
        return f"{age // 60} мин назад"
    if age < 86400:
        return f"{age // 3600} ч назад"
    return datetime.fromtimestamp(checked_at).strftime("%d.%m.%Y %H:%M")


def ping_tooltip(row: ProfileRow, now: float) -> str:
    """Подсказка к задержке: причина отказа, время проверки и текст ядра.

    Пустая строка — подсказки нет: сервер не проверялся.
    """
    lines: list[str] = []
    if row.probe_failure is not None:
        lines.append(FAILURE_REASONS.get(row.probe_failure, ""))
    elif row.latency_ms is None or row.latency_ms < 0:
        return ""
    if row.checked_at > 0:
        lines.append(CHECKED_PREFIX + checked_text(row.checked_at, now))
    if row.probe_failure is not None and row.probe_detail:
        lines.append(row.probe_detail)
    return "\n".join(line for line in lines if line)


def _latency_of(profile: Any) -> int:
    latency = getattr(profile, "latency_ms", -1)
    return -1 if latency is None else int(latency)


def _failure_of(profile: Any) -> ProbeFailure | None:
    return getattr(profile, "probe_failure", None)


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
        # Отказавшие и непроверенные остаются в конце в обоих направлениях:
        # сортировка одним ключом с reverse переставила бы их в начало убывающего
        # порядка, и колонка «Задержка» начиналась бы с пустых значений.
        def by_name(p: Any) -> str:
            return (p.name or "").lower()

        failed = sorted((p for p in profiles if _failure_of(p) is not None), key=by_name)
        rest = [p for p in profiles if _failure_of(p) is None]
        measured = [p for p in rest if _latency_of(p) >= 0]
        untested = sorted((p for p in rest if _latency_of(p) < 0), key=by_name)
        measured.sort(key=_latency_of, reverse=not ascending)
        return measured + failed + untested

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
                probe_failure=_failure_of(profile),
                probe_detail=getattr(profile, "probe_detail", "") or "",
                checked_at=int(getattr(profile, "checked_at", 0) or 0),
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


def selected_text(name: str) -> str:
    """Caption of the selection row under the list: the name without its flag."""
    if not name:
        return SELECTED_NONE
    return SELECTED_PREFIX + split_flag_prefix(name)[1]


def group_count_text(row: GroupRow, progress: Any = None) -> str:
    """Число серверов, а во время замера группы — «готово / всего»."""
    state = progress.state(row.group_id) if progress is not None else None
    if state is None:
        return str(row.count)
    done, total = state
    return f"{done} / {total}"


def group_details(row: GroupRow, progress: Any = None, details: str = "") -> str:
    """Group line after its title: count, progress of a latency run, subscription info.

    `progress` — `PingProgress` или None; `details` — трафик и срок подписки.
    """
    parts = [f"Серверов: {row.count}"]
    if progress is not None and progress.state(row.group_id) is not None:
        parts.append(f"Проверено: {group_count_text(row, progress)}")
    if details:
        parts.append(details)
    return GROUP_SEPARATOR.join(parts)


def group_summary(row: GroupRow, progress: Any = None, details: str = "") -> str:
    """Whole group line as Qt draws it in one cell."""
    return f"{row.title}{GROUP_SEPARATOR}{group_details(row, progress, details)}"
