"""Tests for profile list filtering and sorting (no GTK needed)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.probe_result import ProbeFailure
from src.ui.logic.profiles_view import (
    ProfileRow,
    SortKey,
    build_profile_rows,
    ping_is_failure,
    ping_text,
    ping_tooltip,
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
    probe_failure: ProbeFailure | None = None
    probe_detail: str = ""
    checked_at: int = 0


def profile(
    pid: int,
    name: str,
    ptype: str = "vless",
    addr: str = "a.example:443",
    ping: int = -1,
    failure: ProbeFailure | None = None,
):
    return FakeProfile(
        id=pid,
        name=name,
        proxy_type=ptype,
        bean=FakeBean(addr),
        latency_ms=ping,
        probe_failure=failure,
    )


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


def row(latency_ms=-1, failure=None, checked_at=0, detail=""):
    return ProfileRow(
        profile_id=1,
        title="A",
        proxy_type="vless",
        address="a:443",
        latency_ms=latency_ms,
        is_active=False,
        probe_failure=failure,
        probe_detail=detail,
        checked_at=checked_at,
    )


def test_ping_text():
    assert ping_text(row()) == "—"
    assert ping_text(row(42)) == "42 мс"
    assert ping_text(row(failure=ProbeFailure.TIMEOUT)) == "нет ответа"
    assert ping_text(row(failure=ProbeFailure.UNREACHABLE)) == "нет связи"
    for failure in (
        ProbeFailure.BAD_RESPONSE,
        ProbeFailure.INVALID_CONFIG,
        ProbeFailure.REJECTED,
        ProbeFailure.CORE_FAILED,
    ):
        assert ping_text(row(failure=failure)) == "ошибка"


def test_ping_is_failure_only_for_a_failed_probe():
    assert ping_is_failure(row(failure=ProbeFailure.REJECTED))
    assert not ping_is_failure(row())
    assert not ping_is_failure(row(42))


NOW = 1_800_000_000


def test_ping_tooltip_explains_the_failure_with_time_and_detail():
    text = ping_tooltip(
        row(failure=ProbeFailure.REJECTED, checked_at=NOW - 5 * 60, detail="invalid password"),
        NOW,
    )

    assert text == "Ядро отвергло параметры сервера\nПроверено: 5 мин назад\ninvalid password"


def test_ping_tooltip_names_the_timeout():
    text = ping_tooltip(row(failure=ProbeFailure.TIMEOUT, checked_at=NOW), NOW)

    assert text == "Сервер не ответил за 3 с\nПроверено: только что"


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (30, "только что"),
        (-10, "только что"),
        (59 * 60, "59 мин назад"),
        (3 * 3600, "3 ч назад"),
    ],
)
def test_ping_tooltip_relative_time(age, expected):
    assert ping_tooltip(row(42, checked_at=NOW - age), NOW) == f"Проверено: {expected}"


def test_ping_tooltip_shows_a_date_for_old_checks():
    from datetime import datetime

    old = NOW - 3 * 86400
    expected = datetime.fromtimestamp(old).strftime("%d.%m.%Y %H:%M")

    assert ping_tooltip(row(42, checked_at=old), NOW) == f"Проверено: {expected}"


def test_ping_tooltip_is_empty_without_a_check():
    assert ping_tooltip(row(), NOW) == ""
    assert ping_tooltip(row(42), NOW) == ""  # старый файл: время неизвестно
    assert ping_tooltip(row(failure=ProbeFailure.UNREACHABLE), NOW) == (
        "Ядро не смогло соединиться с сервером"
    )


def test_rows_carry_the_probe_failure(sample):
    groups, profiles = sample
    profiles[1][1].probe_failure = ProbeFailure.TIMEOUT
    profiles[1][1].probe_detail = "ReadTimeout"
    profiles[1][1].checked_at = 1700

    rows = build_profile_rows(groups, profiles, query="бета")
    child = rows[0].children[0]

    assert (child.probe_failure, child.probe_detail, child.checked_at) == (
        ProbeFailure.TIMEOUT,
        "ReadTimeout",
        1700,
    )


@pytest.mark.parametrize("ascending", [True, False])
def test_sort_by_ping_puts_failed_between_measured_and_untested(sample, ascending):
    groups, profiles = sample
    profiles[1] = [
        profile(10, "Я-непроверен"),
        profile(11, "Б-отказ", failure=ProbeFailure.TIMEOUT),
        profile(12, "А-отказ", failure=ProbeFailure.REJECTED),
        profile(13, "В-медленный", ping=300),
        profile(14, "Г-быстрый", ping=50),
        profile(15, "А-непроверен"),
    ]

    rows = build_profile_rows(
        groups, profiles, query="работа", sort_key=SortKey.PING, ascending=ascending
    )
    measured = [14, 13] if ascending else [13, 14]
    assert [c.profile_id for c in rows[0].children] == [*measured, 12, 11, 15, 10]


def test_empty_group_is_hidden_without_a_query():
    """The store always creates a "Default" group; an empty one is noise."""
    groups = {0: FakeGroup(id=0, name="Default")}
    rows = build_profile_rows(groups, {0: []})
    assert rows == []


def test_no_results_text_is_shared():
    from src.ui.logic.profiles_view import NO_RESULTS_TEXT, SELECTED_NONE, selected_text

    assert NO_RESULTS_TEXT == "Ничего не найдено. Измените запрос."
    assert SELECTED_NONE == "Сервер не выбран"
    assert selected_text("🇩🇪 Берлин") == "Выбран: Берлин"
    assert selected_text("Берлин") == "Выбран: Берлин"
    assert selected_text("") == SELECTED_NONE


def test_group_summary_counts_progress_and_details():
    from src.ui.logic.latency import PingProgress
    from src.ui.logic.profiles_view import GroupRow, ProfileRow, group_details, group_summary

    child = ProfileRow(1, "A", "vless", "a:1", -1, False)
    row = GroupRow(10, "Default", "folder-symbolic", False, (child, child))
    assert group_details(row) == "Серверов: 2"
    assert group_summary(row) == "Default  ·  Серверов: 2"

    progress = PingProgress({10: [1, 2]})
    progress.record(1)
    assert group_details(row, progress) == "Серверов: 2  ·  Проверено: 1 / 2"
    assert group_details(row, None, "1 ГБ") == "Серверов: 2  ·  1 ГБ"
