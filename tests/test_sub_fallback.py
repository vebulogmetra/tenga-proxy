"""Разовая загрузка подписки с запасного адреса."""

import pytest
import requests

from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.fallback import (
    FallbackExhaustedError,
    can_propose_after,
    display_error,
    is_worth_trying,
    usable_url,
)
from src.sub.url_policy import SubscriptionPolicyError

PRIMARY = "https://provider.example/sub/token"
BACKUP = "https://backup.example/sub/token"


@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError(),
        requests.Timeout(),
        SubscriptionHttpError(500),
        SubscriptionHttpError(503),
        SubscriptionHttpError(403),
        SubscriptionHttpError(429),
    ],
)
def test_access_failures_are_worth_the_fallback(error):
    assert is_worth_trying(error)


@pytest.mark.parametrize(
    "error",
    [
        SubscriptionHttpError(404),
        SubscriptionHttpError(410),
        SubscriptionHttpError(400),
        SubscriptionHttpError(401),
        SubscriptionTooLargeError(1),
        SubscriptionPolicyError("запрещено"),
        RuntimeError("boom"),
    ],
)
def test_definitive_answers_are_not_worth_the_fallback(error):
    assert not is_worth_trying(error)


def test_a_stored_address_is_usable_after_trimming():
    assert usable_url(PRIMARY, f"  {BACKUP} ") == BACKUP


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "   ",
        "http://backup.example/sub",
        "https://192.168.1.1/sub",
        "https://localhost/sub",
        PRIMARY,
        "https://PROVIDER.example:443/sub/token",
    ],
)
def test_a_stored_address_is_not_trusted(stored):
    assert usable_url(PRIMARY, stored) is None


def test_a_server_answer_explains_more_than_a_lost_connection():
    primary = requests.ConnectionError()
    fallback = SubscriptionHttpError(403)

    assert display_error(primary, fallback) is fallback


@pytest.mark.parametrize("fallback", [requests.ConnectionError(), SubscriptionHttpError(503)])
def test_otherwise_the_primary_error_is_shown(fallback):
    primary = SubscriptionHttpError(502)

    assert display_error(primary, fallback) is primary


@pytest.mark.parametrize(
    "error",
    [
        FallbackExhaustedError(requests.ConnectionError()),
        SubscriptionHttpError(404),
        SubscriptionHttpError(410),
    ],
)
def test_no_permanent_change_is_proposed_when_it_cannot_help(error):
    assert not can_propose_after(error)


@pytest.mark.parametrize(
    "error", [requests.ConnectionError(), SubscriptionHttpError(401), RuntimeError("boom")]
)
def test_a_permanent_change_is_proposed_after_other_failures(error):
    assert can_propose_after(error)


def test_the_exhausted_error_does_not_quote_the_address():
    inner = requests.ConnectionError(f"failed: {PRIMARY}")

    error = FallbackExhaustedError(inner)

    assert error.display_error is inner
    assert PRIMARY not in str(error)
