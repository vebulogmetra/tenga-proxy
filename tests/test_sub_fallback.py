"""Разовая загрузка подписки с запасного адреса."""

from unittest.mock import patch

import pytest
import requests

from src.db.profiles import ProfileManager
from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.fallback import (
    FallbackExhaustedError,
    can_propose_after,
    display_error,
    is_worth_trying,
    usable_url,
)
from src.sub.updater import SubscriptionUpdater
from src.sub.url_policy import SubscriptionPolicyError

PRIMARY = "https://provider.example/sub/token"
BACKUP = "https://backup.example/sub/token"
LINK = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"
LINK_BACKUP = "vless://11111111-1111-1111-1111-111111111111@de.example.org:443?type=tcp#DE-1"


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


def _response(body: str = LINK, status: int = 200, headers: dict | None = None):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response._content_consumed = True
    response.headers = headers or {}
    return response


@pytest.fixture
def subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(SubscriptionUpdater, "RETRY_BASE_DELAY_SEC", 0)
    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Sub", is_subscription=True)
    group.subscription_url = PRIMARY
    group.sub_fallback_url = BACKUP
    return profiles, group


def _serve(routes: dict):
    """A pinned_get replacement: answers by URL and records the requests."""
    requested = []

    def pinned_get(url, **_kwargs):
        requested.append(url)
        answer = routes[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return pinned_get, requested


def _update(profiles, group, routes, group_id="group"):
    pinned_get, requested = _serve(routes)
    updater = SubscriptionUpdater(profiles=profiles)
    target = group.id if group_id == "group" else group_id
    with patch("src.sub.updater.pinned_get", pinned_get):
        beans = updater.update(PRIMARY, group_id=target)
    return updater, beans, requested


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("primary down"),
        _response("down", status=503),
        _response("denied", status=403),
    ],
)
def test_a_failed_primary_loads_the_fallback_once(subscription, failure):
    profiles, group = subscription

    updater, beans, requested = _update(
        profiles, group, {PRIMARY: failure, BACKUP: _response(LINK_BACKUP)}
    )

    assert [bean.name for bean in beans] == ["DE-1"]
    assert requested[-1] == BACKUP
    assert requested.count(BACKUP) == 1
    assert updater.used_fallback_url == BACKUP
    assert group.subscription_url == PRIMARY
    assert group.sub_via_fallback is True
    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["DE-1"]


def test_the_next_update_starts_with_the_primary_and_clears_the_mark(subscription):
    profiles, group = subscription
    _update(profiles, group, {PRIMARY: _response("down", 503), BACKUP: _response(LINK_BACKUP)})

    updater, _beans, requested = _update(profiles, group, {PRIMARY: _response(LINK)})

    assert requested == [PRIMARY]
    assert updater.used_fallback_url == ""
    assert group.sub_via_fallback is False


@pytest.mark.parametrize("status", [404, 410, 400])
def test_a_definitive_answer_does_not_reach_the_fallback(subscription, status):
    profiles, group = subscription

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("no", status=status)})


def test_an_empty_primary_answer_does_not_reach_the_fallback(subscription):
    profiles, group = subscription

    _updater, beans, requested = _update(profiles, group, {PRIMARY: _response("")})

    assert beans == []
    assert requested == [PRIMARY]
    assert group.sub_empty is True


def test_both_addresses_failing_keeps_the_group_and_reports_the_better_error(subscription):
    profiles, group = subscription

    with pytest.raises(FallbackExhaustedError) as caught:
        _update(
            profiles,
            group,
            {PRIMARY: requests.ConnectionError("down"), BACKUP: _response("denied", status=403)},
        )

    assert isinstance(caught.value.display_error, SubscriptionHttpError)
    assert caught.value.display_error.status_code == 403
    assert group.sub_via_fallback is False
    assert group.sub_fallback_url == BACKUP


def test_a_policy_denial_of_the_fallback_counts_as_its_failure(subscription):
    profiles, group = subscription

    with pytest.raises(FallbackExhaustedError) as caught:
        _update(
            profiles,
            group,
            {PRIMARY: _response("down", 503), BACKUP: SubscriptionPolicyError("запрещено")},
        )

    assert caught.value.display_error.status_code == 503


def test_without_a_group_id_nobody_elses_fallback_is_used(subscription):
    profiles, group = subscription
    profiles.current_group_id = group.id

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("down", 503)}, group_id=None)


@pytest.mark.parametrize("stored", ["http://192.168.1.1/sub", PRIMARY, ""])
def test_an_unusable_stored_address_is_not_requested(subscription, stored):
    profiles, group = subscription
    group.sub_fallback_url = stored

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("down", 503)})


def test_a_primary_answer_with_servers_forgets_a_withdrawn_address(subscription):
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response(LINK)})

    assert group.sub_fallback_url == ""


def test_an_unsafe_address_in_a_primary_answer_forgets_the_old_one(subscription):
    profiles, group = subscription

    _update(
        profiles,
        group,
        {PRIMARY: _response(LINK, headers={"fallback-url": "http://192.168.1.1/sub"})},
    )

    assert group.sub_fallback_url == ""


def test_an_empty_primary_answer_keeps_the_address(subscription):
    """Страница CDN с кодом 200 разбирается как пустой список."""
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response("<html>maintenance</html>")})

    assert group.sub_fallback_url == BACKUP


def test_a_fallback_answer_without_the_header_keeps_the_address(subscription):
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response("down", 503), BACKUP: _response(LINK_BACKUP)})

    assert group.sub_fallback_url == BACKUP


def test_a_fallback_answer_can_update_the_address(subscription):
    profiles, group = subscription
    newer = "https://newer.example/sub/token"

    _update(
        profiles,
        group,
        {
            PRIMARY: _response("down", 503),
            BACKUP: _response(LINK_BACKUP, headers={"fallback-url": newer}),
        },
    )

    assert group.sub_fallback_url == newer


def test_the_mark_survives_saving_and_loading(subscription, tmp_path):
    profiles, group = subscription
    group.sub_via_fallback = True
    profiles.save()

    reloaded = ProfileManager(profiles_dir=tmp_path)
    reloaded.load()

    assert reloaded.get_group(group.id).sub_via_fallback is True
