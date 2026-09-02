"""Tests for the dialog form validation (no GTK needed)."""

from __future__ import annotations

import pytest

from src.ui.logic.forms import (
    parse_host_list,
    validate_group_name,
    validate_profile_link,
    validate_subscription,
)

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Name"


def test_a_valid_link_is_accepted():
    result = validate_profile_link(LINK)
    assert result.ok
    assert result.bean is not None


def test_an_empty_link_asks_for_input():
    result = validate_profile_link("   ")
    assert not result.ok
    assert result.message == "Введите ссылку подключения"


def test_an_unparsable_link_is_rejected():
    result = validate_profile_link("not a link")
    assert not result.ok
    assert "разобрать" in result.message


def test_the_link_is_trimmed_before_parsing():
    """Ссылка из буфера часто приходит с переводом строки."""
    assert validate_profile_link(f"  {LINK}\n").ok


def test_a_custom_name_overrides_the_one_from_the_link():
    result = validate_profile_link(LINK, name="Mine")
    assert result.bean.name == "Mine"


def test_an_empty_custom_name_keeps_the_one_from_the_link():
    result = validate_profile_link(LINK, name="  ")
    assert result.bean.name == "Name"


def test_a_valid_link_reports_the_protocol():
    """Подсказка под полем должна называть разобранный протокол."""
    result = validate_profile_link(LINK)
    assert "VLESS" in result.message


def test_a_subscription_needs_a_name():
    result = validate_subscription("", "https://example.com/sub")
    assert not result.ok
    assert "название" in result.message.lower()


def test_a_subscription_needs_a_url():
    result = validate_subscription("Sub", "")
    assert not result.ok
    assert "url" in result.message.lower()


@pytest.mark.parametrize("url", ["ftp://example.com", "example.com", "//example.com"])
def test_a_subscription_url_must_be_http(url):
    result = validate_subscription("Sub", url)
    assert not result.ok
    assert "http" in result.message.lower()


@pytest.mark.parametrize("url", ["http://example.com/s", "https://example.com/s"])
def test_a_valid_subscription_is_accepted(url):
    result = validate_subscription("Sub", url)
    assert result.ok
    assert result.value == ("Sub", url)


def test_subscription_fields_are_trimmed():
    result = validate_subscription("  Sub  ", "  https://example.com  ")
    assert result.value == ("Sub", "https://example.com")


def test_a_group_needs_a_name():
    assert not validate_group_name("   ").ok


def test_a_group_name_is_trimmed():
    assert validate_group_name("  Home  ").value == "Home"


def test_a_host_list_splits_on_newlines_and_commas():
    assert parse_host_list("a.com\nb.com, c.com") == ["a.com", "b.com", "c.com"]


def test_a_host_list_drops_blanks_and_duplicates():
    """Дубликаты в правилах маршрутизации бесполезны и путают счётчик."""
    assert parse_host_list("a.com\n\n a.com \n b.com\n") == ["a.com", "b.com"]


def test_a_host_list_keeps_the_typed_order():
    assert parse_host_list("z.com\na.com") == ["z.com", "a.com"]


def test_an_empty_host_list_is_empty():
    assert parse_host_list("  \n \n") == []


def test_a_host_list_of_none_is_empty():
    assert parse_host_list(None) == []
