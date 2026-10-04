"""Разбор записей списков маршрутизации.

Строка списка превращается в то, что понимает ядро. Ошибка разбора обходится
дорого: непонятую запись ядро либо молча не применяет, либо отвергает вместе со
всем конфигом.
"""

import pytest

from src.db.config import RoutingSettings


def parse(*entries: str) -> tuple[list[str], list[str]]:
    return RoutingSettings().parse_entries(list(entries))


def test_dotted_domain_matches_itself_and_subdomains():
    """Голую строку ядро считает подстрокой: `ok.ru` совпал бы с `facebook.ru`."""
    assert parse("ok.ru") == (["domain:ok.ru"], [])


@pytest.mark.parametrize("entry", ["*.example.com", ".example.com", "Example.COM"])
def test_wildcard_and_case_are_normalized(entry):
    assert parse(entry) == (["domain:example.com"], [])


def test_word_without_dot_stays_a_keyword():
    assert parse("google") == (["google"], [])


@pytest.mark.parametrize(
    "entry",
    ["domain:example.com", "full:example.com", "regexp:^a\\.example$", "keyword:video"],
)
def test_core_prefixes_pass_through(entry):
    assert parse(entry) == ([entry], [])


def test_geosite_goes_to_domains():
    assert parse("geosite:category-ru", "GeoSite:Google@cn", "geosite:geolocation-!cn") == (
        ["geosite:category-ru", "geosite:google@cn", "geosite:geolocation-!cn"],
        [],
    )


def test_geoip_goes_to_ips():
    """Раньше `geoip:ru` попадал в домены и молча не работал."""
    assert parse("geoip:ru", "GEOIP:Private") == ([], ["geoip:ru", "geoip:private"])


@pytest.mark.parametrize(
    "entry", ["geoip:", "geosite:", "geoip:ru@attr", "geosite:bad name", "geoip:!ru"]
)
def test_malformed_geo_entry_is_dropped(entry):
    """Похожее на geo, но невалидное: в домены не проваливается."""
    assert parse(entry) == ([], [])


def test_ipv4_address_and_cidr():
    assert parse("1.2.3.4", "10.0.0.0/8") == ([], ["1.2.3.4/32", "10.0.0.0/8"])


def test_ipv6_address_and_cidr():
    assert parse("::1", "fc00::/7") == ([], ["::1/128", "fc00::/7"])


@pytest.mark.parametrize("entry", ["example.com/24", "1.2.3.4/99", "300.1.1.1/8"])
def test_broken_cidr_is_dropped(entry):
    """Такую запись ядро не примет ни доменом, ни сетью — и отвергнет весь конфиг."""
    assert parse(entry) == ([], [])


def test_comma_separated_line_is_split():
    assert parse("a.example, 1.1.1.1,geoip:ru") == (
        ["domain:a.example"],
        ["1.1.1.1/32", "geoip:ru"],
    )


def test_blank_entries_are_skipped():
    assert parse("", "  ", ",") == ([], [])
