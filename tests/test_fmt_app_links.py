import base64
import json
from urllib.parse import quote

import pytest

from src.fmt.app_links import parse_app_link


def test_subscription_plus_token_is_not_a_space():
    link = parse_app_link(
        "veblock://add/" + quote("https://example.com/sub?token=a+b", safe="") + "#My+name"
    )
    assert link.url == "https://example.com/sub?token=a+b"
    assert link.name == "My name"


def test_routing_lists_are_normalized():
    payload = base64.urlsafe_b64encode(
        json.dumps({"DirectSites": ["https://пример.рф/p"], "GlobalProxy": False}).encode()
    ).decode()
    link = parse_app_link("wingeon://routing/add/" + payload)
    assert link.routing.direct_list == ["xn--e1afmkfd.xn--p1ai"]
    assert link.routing.mode == "custom"


@pytest.mark.parametrize(
    "uri", ["veblock://unknown", "veblock://add/%zz", "veblock://add/https%3A%2F%2Flocalhost%2Fsub"]
)
def test_invalid_or_unsafe_links_are_rejected(uri):
    with pytest.raises(ValueError, match=r"."):
        parse_app_link(uri)


def test_vk_connect_is_explicitly_unsupported():
    assert parse_app_link("veblock://connect?token=secret").operation == "unsupported"


def test_global_proxy_flag_does_not_disable_imported_direct_lists():
    payload = base64.urlsafe_b64encode(
        json.dumps({"DirectSites": ["example.org"], "GlobalProxy": True}).encode()
    ).decode()
    link = parse_app_link("veblock://routing/add/" + payload)
    assert link.routing.mode == "custom"
    assert link.routing.direct_list == ["example.org"]
    assert link.direct_default is False


def test_happ_rules_keep_exact_domains_idn_and_compressed_ipv6():
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "DirectSites": ["full:Пример.РФ", "domain:Example.org", "xn--p1ai"],
                "DirectIp": ["2001:db8::1", "2a00:1450::/32"],
            }
        ).encode()
    ).decode()
    link = parse_app_link("happ://routing/add/" + payload)
    assert link.routing.direct_list == [
        "full:xn--e1afmkfd.xn--p1ai",
        "domain:example.org",
        "xn--p1ai",
        "2001:db8::1",
        "2a00:1450::/32",
    ]


def _routing(fields: dict) -> str:
    return "happ://routing/add/" + base64.urlsafe_b64encode(json.dumps(fields).encode()).decode()


def test_routing_profile_name_is_cleaned_and_bounded():
    link = parse_app_link(_routing({"Name": "RU\x07 direct" + "x" * 100}))
    assert link.name == ("RU direct" + "x" * 100)[:64]


def test_provider_direct_default_is_reported_not_applied():
    link = parse_app_link(_routing({"GlobalProxy": False, "DirectSites": ["example.org"]}))
    assert link.direct_default is True
    assert link.warnings == ()
    assert link.routing.mode == "custom"


def test_non_string_name_is_rejected():
    with pytest.raises(ValueError, match="имя профиля"):
        parse_app_link(_routing({"Name": 5}))
