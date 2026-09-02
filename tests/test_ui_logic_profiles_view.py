"""Tests for profile list filtering and sorting (no GTK needed)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.ui.logic.profiles_view import (
    SortKey,
    build_profile_rows,
    ping_text,
)


@dataclass
class FakeGroup:
    id: int
    name: str
    is_subscription: bool = False


@dataclass
class FakeBean:
    display_address: str


@dataclass
class FakeProfile:
    id: int
    name: str
    proxy_type: str
    bean: FakeBean
    latency_ms: int = -1


def profile(pid: int, name: str, ptype: str = "vless", addr: str = "a.example:443", ping: int = -1):
    return FakeProfile(id=pid, name=name, proxy_type=ptype, bean=FakeBean(addr), latency_ms=ping)


@pytest.fixture
def sample():
    """Two groups: a subscription and a plain one."""
    groups = {
        1: FakeGroup(id=1, name="Работа", is_subscription=False),
        2: FakeGroup(id=2, name="Провайдер", is_subscription=True),
    }
    profiles = {
        1: [
            profile(10, "Альфа", "vless", "alfa.example:443", 120),
            profile(11, "Бета", "trojan", "beta.example:8443", -1),
        ],
        2: [
            profile(20, "Гамма", "vmess", "gamma.example:80", 40),
        ],
    }
    return groups, profiles


def test_empty_query_returns_every_group(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles)
    assert len(rows) == 2
    assert sum(len(row.children) for row in rows) == 3


def test_subscriptions_come_first(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles)
    assert [row.group_id for row in rows] == [2, 1]
    assert rows[0].is_subscription is True


def test_query_matches_profile_name(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="альфа")
    assert len(rows) == 1
    assert [child.title for child in rows[0].children] == ["Альфа"]


def test_query_matches_proxy_type(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="trojan")
    assert [child.title for child in rows[0].children] == ["Бета"]


def test_query_matches_address(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="gamma.example")
    assert [child.title for child in rows[0].children] == ["Гамма"]


def test_group_name_match_keeps_every_profile(sample):
    """A group whose own name matches shows all its profiles, not a subset."""
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="работа")
    assert len(rows) == 1
    assert [child.title for child in rows[0].children] == ["Альфа", "Бета"]


def test_group_without_matches_disappears(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="альфа")
    assert [row.group_id for row in rows] == [1]


def test_sort_by_type(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="работа", sort_key=SortKey.TYPE)
    assert [child.proxy_type for child in rows[0].children] == ["trojan", "vless"]

    rows = build_profile_rows(
        groups, profiles, query="работа", sort_key=SortKey.TYPE, ascending=False
    )
    assert [child.proxy_type for child in rows[0].children] == ["vless", "trojan"]


def test_sort_by_ping_puts_untested_last(sample):
    """latency_ms < 0 means "not measured" and must never sort as the fastest."""
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="работа", sort_key=SortKey.PING)
    assert [child.latency_ms for child in rows[0].children] == [120, -1]


def test_sort_by_ping_keeps_untested_last_when_descending(sample):
    """Reversing the order must not float the dashes to the top of the column."""
    groups, profiles = sample
    profiles[1].append(profile(12, "Дельта", "vless", "delta.example:443", 300))

    rows = build_profile_rows(
        groups, profiles, query="работа", sort_key=SortKey.PING, ascending=False
    )
    assert [child.latency_ms for child in rows[0].children] == [300, 120, -1]


def test_active_profile_is_marked(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, active_profile_id=20)
    active = [child for row in rows for child in row.children if child.is_active]
    assert [child.profile_id for child in active] == [20]


def test_group_icon_depends_on_kind(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles)
    icons = {row.group_id: row.icon_name for row in rows}
    assert icons[2] == "network-server-symbolic"
    assert icons[1] == "folder-symbolic"


def test_group_title_carries_visible_count(sample):
    groups, profiles = sample
    rows = build_profile_rows(groups, profiles, query="альфа")
    assert rows[0].title == "Работа"
    assert rows[0].count == 1


def test_ping_text():
    assert ping_text(-1) == "—"
    assert ping_text(42) == "42 ms"
