import json

import pytest

from src.diag.catalog import (
    RUSSIAN_REFERENCES,
    CatalogError,
    DiagnosticPurpose,
    PlacementRegistry,
    is_public_address,
    load_catalog,
    parse_catalog,
)
from src.diag.models import AddressFamily


def raw_catalog(**changes):
    target = {"id": "one", "hostname": "one.example.org", "placementGroup": "a"}
    target.update(changes)
    other = {"id": "two", "hostname": "two.example.org", "placementGroup": "b"}
    return json.dumps(
        {
            "schemaVersion": 1,
            "catalogVersion": 1,
            "expiresAtEpochSeconds": 100,
            "targets": [target, other],
        }
    )


def test_bundled_catalog_loads_v6_and_keeps_ipv4_only():
    catalog = load_catalog()
    assert catalog.catalog_version == 6
    assert {t.id for t in catalog.targets} >= {
        "mozilla-success", "cloudflare-trace", "google-web", "yandex-main", "vk-web",
        "telegram-web", "instagram-web", "youtube-web", "youtube-public-video",
    }  # fmt: skip
    assert catalog.target("google-connect").expected_status == 204
    assert all(t.families == (AddressFamily.IPV4,) for t in catalog.targets)


def test_dns_targets_exclude_instagram():
    ids = {t.id for t in load_catalog().dns_targets()}
    assert "instagram-web" not in ids and "instagram-public-icon" not in ids
    assert "yandex-main" in ids


def test_baseline_groups_are_six():
    groups = {
        t.placement_group for t in load_catalog().targets if t.purpose is DiagnosticPurpose.BASELINE
    }
    assert groups == {"fastly", "cloudflare", "google", "github", "yandex", "vk"}


def test_stale_catalog_is_detected():
    catalog = load_catalog()
    assert not catalog.is_stale(now=catalog.expires_at - 1)
    assert catalog.is_stale(now=catalog.expires_at)


@pytest.mark.parametrize(
    "changes",
    [
        {"hostname": "localhost"},
        {"hostname": "printer.local"},
        {"hostname": "UPPER.example.org"},
        {"port": 8443},
        {"path": "//evil"},
        {"path": "/a?b=1"},
        {"maxBytes": 0},
        {"maxBytes": 65537},
        {"expectedStatus": 302},
        {"id": "Bad Id"},
        {"families": []},
    ],
)
def test_parse_rejects_unsafe_targets(changes):
    with pytest.raises(CatalogError):
        parse_catalog(raw_catalog(**changes))


def test_parse_rejects_duplicates_and_broken_json():
    raw = json.loads(raw_catalog())
    raw["targets"][1]["id"] = "one"
    with pytest.raises(CatalogError):
        parse_catalog(json.dumps(raw))
    with pytest.raises(CatalogError):
        parse_catalog("{")
    with pytest.raises(CatalogError):
        parse_catalog(json.dumps({"schemaVersion": 1, "catalogVersion": 6, "targets": [{}]}))


def test_missing_file_is_a_catalog_error(tmp_path):
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "absent.json")


def test_placement_registry_verifies_known_prefix():
    registry = PlacementRegistry.load()
    target = load_catalog().target("cloudflare-trace")
    assert registry.group(target, "104.16.112.1", now=1) == "cloudflare"
    assert registry.group(target, "198.41.0.4", now=1) is None
    assert registry.group(target, "10.0.0.1", now=1) is None


def test_placement_registry_expires():
    registry = PlacementRegistry.load()
    target = load_catalog().target("cloudflare-trace")
    assert registry.groups(now=1) == {"fastly", "cloudflare", "google", "github", "yandex", "vk"}
    assert registry.groups(now=2**40) == frozenset()
    assert registry.group(target, "104.16.112.1", now=2**40) is None


def test_placement_registry_rejects_overlap_across_groups():
    doc = lambda tid, group, prefix: {  # noqa: E731
        "target": {"id": tid, "hostname": f"{tid}.example.org", "placementGroup": group},
        "prefixes": [prefix],
    }
    raw = {
        "schemaVersion": 1,
        "expiresAtEpochSeconds": 100,
        "entries": [doc("aa", "a", "1.1.1.0/24"), doc("bb", "b", "1.1.0.0/16")],
    }
    with pytest.raises(CatalogError):
        PlacementRegistry.parse(json.dumps(raw))


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("1.1.1.1", True),
        ("8.8.8.8", True),
        ("10.0.0.1", False),
        ("127.0.0.1", False),
        ("0.0.0.0", False),
        ("169.254.1.1", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("100.64.0.1", False),
        ("198.18.0.1", False),
        ("203.0.113.5", False),
        ("224.0.0.1", False),
        ("2606:4700:4700::1111", True),
        ("2001:db8::1", False),
        ("fe80::1", False),
        ("not an ip", False),
    ],
)
def test_public_address_policy(address, public):
    assert is_public_address(address) is public


def test_russian_references():
    assert frozenset({"yandex.ru", "ya.ru", "vk.com", "ok.ru"}) == RUSSIAN_REFERENCES
