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
    sub_user_info: str = ""
    sub_announce: str = ""
    sub_support_url: str = ""
    sub_web_page_url: str = ""


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


# --- Сообщение об ошибке обновления -------------------------------------------


def test_access_denied_is_described_with_the_providers_text():
    from src.sub.errors import SubscriptionHttpError
    from src.ui.logic.subscriptions_view import describe_update_error

    text = describe_update_error(SubscriptionHttpError(403, "Превышен лимит устройств"))

    assert text == "сервер ответил 403: Превышен лимит устройств"


def test_other_http_errors_are_described_by_code():
    from src.sub.errors import SubscriptionHttpError
    from src.ui.logic.subscriptions_view import describe_update_error

    assert describe_update_error(SubscriptionHttpError(404, "Not Found")) == "сервер ответил 404"


def test_too_large_response_is_described():
    from src.sub.errors import SubscriptionTooLargeError
    from src.ui.logic.subscriptions_view import describe_update_error

    assert describe_update_error(SubscriptionTooLargeError(11 * 1024 * 1024)) == (
        "ответ сервера больше 10 МБ"
    )


def test_network_errors_do_not_leak_the_subscription_address():
    """Текст ошибки requests содержит полный URL, а в нём — токен подписки."""
    import requests

    from src.ui.logic.subscriptions_view import describe_update_error

    refused = requests.ConnectionError("HTTPSConnectionPool(host='x'): /sub/secret-token")
    timeout = requests.Timeout("Read timed out: /sub/secret-token")

    assert describe_update_error(refused) == "нет связи с сервером подписки"
    assert describe_update_error(timeout) == "сервер подписки не ответил вовремя"


def test_unknown_errors_fall_back_to_their_text():
    from src.ui.logic.subscriptions_view import describe_update_error

    assert describe_update_error(ValueError("boom")) == "boom"


# --- Метаданные провайдера ----------------------------------------------------

GIB = 1024**3
NOW = 1_760_000_000  # 09.10.2025


def _row(**fields):
    group = FakeGroup(id=1, name="Основная", subscription_url="https://sub.example/main", **fields)
    return build_subscription_rows({1: group}, {1: 3}, now=NOW)[0]


def test_row_without_metadata_has_no_details():
    row = _row()

    assert row.details_text == ""
    assert row.announce == ""
    assert not row.expired


def test_usage_shows_used_and_total():
    row = _row(sub_user_info=f"upload={GIB}; download={2 * GIB}; total={10 * GIB}; expire=0")

    assert row.usage_text == "3.00 GB из 10.00 GB"


def test_unlimited_usage_says_so():
    row = _row(sub_user_info=f"upload=0; download={GIB}; total=0; expire=0")

    assert row.usage_text == "1.00 GB, без лимита"


def test_expiry_in_the_future():
    expire = NOW + 30 * 86400
    row = _row(sub_user_info=f"upload=0; download=0; total=0; expire={expire}")

    date = datetime.datetime.fromtimestamp(expire).strftime("%d.%m.%Y")
    assert row.expire_text == f"до {date}"
    assert not row.expired


def test_expiry_in_the_past_is_flagged():
    expire = NOW - 86400
    row = _row(sub_user_info=f"upload=0; download=0; total=0; expire={expire}")

    date = datetime.datetime.fromtimestamp(expire).strftime("%d.%m.%Y")
    assert row.expire_text == f"истекла {date}"
    assert row.expired


def test_details_join_usage_and_expiry():
    expire = NOW + 86400
    row = _row(sub_user_info=f"upload=0; download={GIB}; total={2 * GIB}; expire={expire}")

    assert row.details_text == f"{row.usage_text} · {row.expire_text}"


def test_garbage_user_info_is_ignored():
    assert _row(sub_user_info="what is this").details_text == ""


def test_announce_and_links_reach_the_row():
    row = _row(
        sub_announce="Техработы до 12:00",
        sub_support_url="https://t.me/provider",
        sub_web_page_url="https://provider.example/account",
    )

    assert row.announce == "Техработы до 12:00"
    assert row.support_url == "https://t.me/provider"
    assert row.web_page_url == "https://provider.example/account"


def test_unsafe_links_are_not_offered():
    """Файл профилей можно поправить руками: фильтр стоит и при показе."""
    row = _row(sub_support_url="javascript:alert(1)", sub_web_page_url="http://provider.example")

    assert row.support_url == ""
    assert row.web_page_url == ""
