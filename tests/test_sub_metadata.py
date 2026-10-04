"""Метаданные подписки: заголовки ответа и строки `#key: value` в теле."""

import base64

import pytest

from src.sub.metadata import (
    SubscriptionMetadata,
    SubscriptionUserInfo,
    decode_value,
    metadata_from_body,
    metadata_from_headers,
    parse_body_line,
    read_metadata,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# --- subscription-userinfo ----------------------------------------------------


def test_user_info_is_parsed_from_the_header_string():
    info = SubscriptionUserInfo.from_header(
        "upload=1024; download=2048; total=10737418240; expire=1767225600"
    )

    assert info == SubscriptionUserInfo(
        upload=1024, download=2048, total=10737418240, expire=1767225600
    )
    assert info.used == 3072
    assert not info.is_unlimited


def test_user_info_parsing_is_lenient():
    info = SubscriptionUserInfo.from_header("upload=abc;;download = 5 ;garbage;total=;expire=7")

    assert info == SubscriptionUserInfo(upload=0, download=5, total=0, expire=7)
    assert info.is_unlimited


@pytest.mark.parametrize("header", ["", "   ", "nothing useful", None])
def test_user_info_without_known_keys_is_absent(header):
    assert SubscriptionUserInfo.from_header(header) is None


def test_user_info_round_trips_through_its_header_form():
    info = SubscriptionUserInfo(upload=1, download=2, total=3, expire=4)

    assert info.to_header() == "upload=1; download=2; total=3; expire=4"
    assert SubscriptionUserInfo.from_header(info.to_header()) == info


# --- base64: ------------------------------------------------------------------


def test_base64_prefix_is_decoded_for_any_value():
    assert decode_value(f"base64:{b64('Моя подписка')}") == "Моя подписка"
    assert decode_value(f"BASE64: {b64('Моя подписка')}") == "Моя подписка"


def test_value_without_the_prefix_is_left_alone():
    encoded = b64("Моя подписка")

    assert decode_value(encoded) == encoded


def test_lenient_mode_decodes_without_the_prefix():
    """announce исторически приходит в base64 и без префикса."""
    assert decode_value(b64("Техработы до 12:00"), lenient_base64=True) == "Техработы до 12:00"


@pytest.mark.parametrize("plain", ["Техработы до 12:00", "Maintenance", "News", "hello world"])
def test_lenient_mode_keeps_plain_text(plain):
    assert decode_value(plain, lenient_base64=True) == plain


def test_url_safe_alphabet_is_understood():
    text = "??>>??>>"  # в стандартном алфавите даёт `/` и `+`
    url_safe = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    assert "-" in url_safe or "_" in url_safe

    assert decode_value(f"base64:{url_safe}") == text


def test_broken_base64_keeps_the_raw_value():
    assert decode_value("base64:%%%") == "base64:%%%"
    assert decode_value("base64:" + base64.b64encode(b"\xff\xfe\xfd").decode()) == (
        "base64:" + base64.b64encode(b"\xff\xfe\xfd").decode()
    )


# --- заголовки ----------------------------------------------------------------


def test_headers_are_read_case_insensitively():
    metadata = metadata_from_headers(
        {
            "Subscription-Userinfo": "upload=1; download=2; total=3; expire=4",
            "Profile-Update-Interval": "12",
            "Profile-Title": f"base64:{b64('Быстрый VPN')}",
            "Support-URL": "https://t.me/provider_support",
            "Profile-Web-Page-Url": "https://provider.example/account",
            "Announce": b64("Техработы до 12:00"),
            "Content-Type": "text/plain",
        }
    )

    assert metadata == SubscriptionMetadata(
        user_info=SubscriptionUserInfo(upload=1, download=2, total=3, expire=4),
        update_interval_hours=12,
        title="Быстрый VPN",
        support_url="https://t.me/provider_support",
        web_page_url="https://provider.example/account",
        announce="Техработы до 12:00",
    )


def test_missing_headers_give_empty_metadata():
    assert metadata_from_headers({}) == SubscriptionMetadata()
    assert metadata_from_headers(None) == SubscriptionMetadata()


@pytest.mark.parametrize("value", ["abc", "-5", "", "1.5"])
def test_bad_update_interval_is_zero(value):
    assert metadata_from_headers({"profile-update-interval": value}).update_interval_hours == 0


def test_title_is_a_single_short_line():
    """Заголовок идёт в список и в уведомления: без переводов строк, не длиннее 64."""
    metadata = metadata_from_headers({"profile-title": "My\r\nVPN\x00 " + "x" * 100})

    assert "\n" not in metadata.title
    assert "\x00" not in metadata.title
    assert metadata.title.startswith("MyVPN")
    assert len(metadata.title) == 64


def test_security_related_keys_are_not_recognised():
    """Провайдер не должен управлять настройками клиента через подписку."""
    metadata = metadata_from_headers({"hide-settings": "1", "routing": "happ://routing/add/x"})

    assert metadata == SubscriptionMetadata()


# --- тело ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("#profile-title: Мой VPN", ("profile-title", "Мой VPN")),
        ("#  Profile-Title :  Мой VPN  ", ("profile-title", "Мой VPN")),
        ("#support-url: https://t.me/x", ("support-url", "https://t.me/x")),
        ("# обычный комментарий", None),
        ("#hide-settings: 1", None),
        ("vless://uuid@host:443#name", None),
        ("", None),
    ],
)
def test_body_line(line, expected):
    assert parse_body_line(line) == expected


def test_body_metadata_is_read_from_plain_text():
    body = "#profile-title: Мой VPN\n#profile-update-interval: 6\nvless://uuid@host:443#name\n"

    metadata = metadata_from_body(body)

    assert metadata.title == "Мой VPN"
    assert metadata.update_interval_hours == 6


def test_body_metadata_is_read_from_inside_a_base64_body():
    body = b64("#announce: Техработы\n#support-url: https://t.me/x\nvless://uuid@host:443#name\n")

    metadata = metadata_from_body(body)

    assert metadata.announce == "Техработы"
    assert metadata.support_url == "https://t.me/x"


def test_json_body_has_no_metadata():
    assert metadata_from_body('{"outbounds": []}') == SubscriptionMetadata()


# --- приоритет ----------------------------------------------------------------


def test_body_values_override_headers():
    """CDN режет нестандартные заголовки, а тело провайдер контролирует целиком."""
    headers = {"profile-title": "Из заголовка", "support-url": "https://t.me/from_header"}
    body = "#profile-title: Из тела\nvless://uuid@host:443#name"

    metadata = read_metadata(headers, body)

    assert metadata.title == "Из тела"
    assert metadata.support_url == "https://t.me/from_header"
