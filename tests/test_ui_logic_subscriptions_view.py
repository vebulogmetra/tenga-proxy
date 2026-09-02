"""Tests for the subscription list logic (no GTK needed)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pytest

from src.ui.logic.subscriptions_view import (
    NEVER_UPDATED,
    build_subscription_rows,
    format_updated,
)


@dataclass
class FakeGroup:
    id: int
    name: str
    is_subscription: bool = True
    subscription_url: str = ""
    last_updated: int = 0


@pytest.fixture
def sample():
    groups = {
        1: FakeGroup(
            id=1,
            name="Основная",
            subscription_url="https://sub.example/main",
            last_updated=1_700_000_000,
        ),
        2: FakeGroup(
            id=2,
            name="Запасная",
            subscription_url="https://backup.example/list",
            last_updated=0,
        ),
        3: FakeGroup(id=3, name="Локальные", is_subscription=False),
    }
    counts = {1: 120, 2: 0}
    return groups, counts


def test_format_updated_never():
    assert format_updated(0) == NEVER_UPDATED


def test_format_updated_known_timestamp():
    timestamp = 1_700_000_000
    expected = datetime.datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y %H:%M")
    assert format_updated(timestamp) == expected


def test_plain_groups_are_excluded(sample):
    groups, counts = sample
    rows = build_subscription_rows(groups, counts)
    assert [row.group_id for row in rows] == [1, 2]


def test_profile_count_comes_from_the_mapping(sample):
    groups, counts = sample
    rows = build_subscription_rows(groups, counts)
    assert {row.group_id: row.profile_count for row in rows} == {1: 120, 2: 0}


def test_query_matches_name(sample):
    groups, counts = sample
    rows = build_subscription_rows(groups, counts, query="запас")
    assert [row.name for row in rows] == ["Запасная"]


def test_query_matches_url(sample):
    groups, counts = sample
    rows = build_subscription_rows(groups, counts, query="backup.example")
    assert [row.group_id for row in rows] == [2]


def test_query_matches_updated_text(sample):
    groups, counts = sample
    rows = build_subscription_rows(groups, counts, query="никогда")
    assert [row.group_id for row in rows] == [2]


def test_url_is_not_truncated(sample):
    """The widget ellipsizes; the model keeps the whole URL so filtering works."""
    groups, counts = sample
    groups[1].subscription_url = "https://sub.example/" + "x" * 200
    rows = build_subscription_rows(groups, counts, query="xxxxx")
    assert rows[0].url == groups[1].subscription_url
