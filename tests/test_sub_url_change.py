"""Смена адреса подписки по подсказке провайдера: только предложение, без автозамены."""

from unittest.mock import Mock, patch

import pytest

from src.sub.metadata import SubscriptionMetadata, apply_metadata, metadata_from_headers
from src.sub.updater import SubscriptionUpdater
from src.sub.url_change import (
    REASON_FALLBACK_URL,
    REASON_NEW_URL,
    UrlChangeProposal,
    is_acceptable_subscription_url,
    propose_url_change,
)

CURRENT = "https://provider.example/sub/token"
LINK = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"


@pytest.mark.parametrize(
    "url",
    ["https://new.example/sub/token", "http://new.example:8080/sub", "https://93.184.216.34/sub"],
)
def test_public_http_addresses_are_acceptable(url):
    assert is_acceptable_subscription_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "vless://uuid@host:443",
        "ftp://new.example/sub",
        "https://",
        "https://localhost/sub",
        "https://router.local/sub",
        "http://127.0.0.1:8080/sub",
        "http://10.0.0.5/sub",
        "http://172.16.3.1/sub",
        "http://192.168.1.1/sub",
        "http://169.254.1.1/sub",
        "http://[::1]/sub",
        "http://[fe80::1]/sub",
        "http://[fc00::1]/sub",
        "https://new.example/" + "x" * 2048,
    ],
)
def test_other_addresses_are_not(url):
    """Провайдер не должен отправлять клиента на локальные адреса и чужие схемы."""
    assert not is_acceptable_subscription_url(url)


def test_a_different_acceptable_address_becomes_a_proposal():
    proposal = propose_url_change(7, CURRENT, "  https://new.example/sub  ", REASON_NEW_URL)

    assert proposal == UrlChangeProposal(
        group_id=7, new_url="https://new.example/sub", reason=REASON_NEW_URL
    )


@pytest.mark.parametrize("candidate", ["", None, CURRENT, f"  {CURRENT} ", "http://192.168.1.1/s"])
def test_nothing_is_proposed_for_an_empty_same_or_unsafe_address(candidate):
    assert propose_url_change(7, CURRENT, candidate, REASON_NEW_URL) is None


def test_both_addresses_are_read_from_the_response():
    metadata = metadata_from_headers(
        {"New-Url": "https://new.example/sub", "Fallback-Url": "https://backup.example/sub"}
    )

    assert metadata.new_url == "https://new.example/sub"
    assert metadata.fallback_url == "https://backup.example/sub"


def _group():
    from src.db.profiles import ProfileGroup

    return ProfileGroup(id=1, name="Sub", is_subscription=True, subscription_url=CURRENT)


def test_the_fallback_address_is_kept_for_a_failed_update():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(fallback_url="https://backup.example/sub"))

    assert group.sub_fallback_url == "https://backup.example/sub"


def test_an_unsafe_fallback_address_is_not_stored():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(fallback_url="http://192.168.1.1/sub"))

    assert group.sub_fallback_url == ""


def test_the_new_address_never_replaces_the_current_one_by_itself():
    group = _group()
    apply_metadata(group, SubscriptionMetadata(new_url="https://new.example/sub"))

    assert group.subscription_url == CURRENT


def test_updater_reports_the_new_address_of_the_last_update(tmp_path):
    from src.db.profiles import ProfileManager

    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Sub", is_subscription=True)
    group.subscription_url = CURRENT
    updater = SubscriptionUpdater(profiles=profiles)

    def response(headers: dict[str, str]) -> Mock:
        mock = Mock()
        mock.text = LINK
        mock.content = LINK.encode("utf-8")
        mock.headers = headers
        mock.raise_for_status = Mock()
        return mock

    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.return_value = response({"new-url": "https://new.example/sub"})
        updater.update(CURRENT, group_id=group.id)
        assert updater.new_url == "https://new.example/sub"
        assert group.subscription_url == CURRENT

        mock_get.return_value = response({})
        updater.update(CURRENT, group_id=group.id)
        assert updater.new_url == ""


@pytest.mark.parametrize(
    "host",
    ["localhost.", "router.local.", "127.0.0.1.", "127.1", "2130706433", "0x7f000001"],
)
def test_local_host_spellings_are_rejected(host):
    """DNS-конечная точка и legacy IPv4 не делают локальный адрес публичным."""
    assert not is_acceptable_subscription_url(f"http://{host}/sub")


@pytest.mark.parametrize("host", ["new.example.", "93.184.216.34."])
def test_public_hosts_with_a_trailing_dot_are_acceptable(host):
    assert is_acceptable_subscription_url(f"https://{host}/sub")


@pytest.mark.parametrize(
    "url",
    [
        "https://new.example:port/sub",
        "https://new.example:99999/sub",
        "https://new.example/sub\r\n?token=abc",
        "https://new.example/\tsub",
        "https://new.example/sub\x00",
    ],
)
def test_malformed_ports_and_control_characters_are_rejected(url):
    assert not is_acceptable_subscription_url(url)
