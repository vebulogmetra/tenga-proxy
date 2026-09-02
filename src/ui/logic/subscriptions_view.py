"""Subscription list logic (GTK-free)."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

NEVER_UPDATED = "Никогда"
_TIME_FORMAT = "%d.%m.%Y %H:%M"


@dataclass(frozen=True)
class SubscriptionRow:
    """One subscription as shown in the list."""

    group_id: int
    name: str
    url: str
    updated_text: str
    profile_count: int


def format_updated(timestamp: int) -> str:
    """Render the last update time, including the "never" case."""
    if not timestamp:
        return NEVER_UPDATED
    return datetime.datetime.fromtimestamp(timestamp).strftime(_TIME_FORMAT)


def build_subscription_rows(
    groups: Mapping[int, Any],
    profile_counts: Mapping[int, int],
    *,
    query: str = "",
) -> list[SubscriptionRow]:
    """Build the subscription list for the given filter.

    URL сохраняется целиком: обрезку делает виджет, а фильтр должен искать по
    полному адресу, иначе часть подписок стала бы ненаходимой.
    """
    normalized = query.strip().lower()

    rows: list[SubscriptionRow] = []
    for group in groups.values():
        if not group.is_subscription:
            continue

        url = group.subscription_url or ""
        updated_text = format_updated(group.last_updated)

        if normalized and not (
            normalized in (group.name or "").lower()
            or normalized in url.lower()
            or normalized in updated_text.lower()
        ):
            continue

        rows.append(
            SubscriptionRow(
                group_id=group.id,
                name=group.name,
                url=url,
                updated_text=updated_text,
                profile_count=profile_counts.get(group.id, 0),
            )
        )

    return rows
