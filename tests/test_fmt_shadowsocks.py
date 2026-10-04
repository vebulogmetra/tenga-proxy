"""Разбор ссылок Shadowsocks: SIP002, legacy и 2022-blake3."""

import base64

import pytest

from src.fmt import parse_link
from src.fmt.protocols import ShadowsocksBean

KEY_16 = base64.b64encode(bytes(range(16))).decode()
# Ключ подобран так, чтобы в base64 были «+», «/» и «=»: на них и ломался разбор.
KEY_32 = base64.b64encode(bytes([0xFB, 0xEF, 0xFF] * 10 + [1, 2])).decode()


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def parse(link: str) -> ShadowsocksBean:
    bean = parse_link(link)
    assert isinstance(bean, ShadowsocksBean), link
    return bean


def test_key_fixture_exercises_special_characters():
    assert "+" in KEY_32 and "/" in KEY_32 and KEY_32.endswith("=")


def test_sip002_base64_userinfo():
    """Самая частая форма: ss://base64(method:password)@host:port#name."""
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388#My%20Server")

    assert bean.method == "aes-256-gcm"
    assert bean.password == "pass"
    assert bean.server_address == "1.2.3.4"
    assert bean.server_port == 8388
    assert bean.name == "My Server"


def test_sip002_userinfo_in_standard_base64_with_padding():
    userinfo = base64.b64encode(b"chacha20-ietf-poly1305:p+ss/w?rd").decode()
    bean = parse(f"ss://{userinfo}@example.com:443#n")

    assert bean.method == "chacha20-ietf-poly1305"
    assert bean.password == "p+ss/w?rd"
    assert bean.server_address == "example.com"


def test_legacy_fully_encoded_link():
    bean = parse("ss://" + b64url("aes-256-gcm:pass@1.2.3.4:8388") + "#n")

    assert (bean.method, bean.password) == ("aes-256-gcm", "pass")
    assert (bean.server_address, bean.server_port) == ("1.2.3.4", 8388)


def test_password_may_contain_colon_and_at():
    bean = parse(f"ss://{b64url('aes-256-gcm:p@ss:word')}@1.2.3.4:8388")
    assert bean.password == "p@ss:word"


def test_ipv6_server():
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@[2001:db8::1]:8388#n")
    assert (bean.server_address, bean.server_port) == ("2001:db8::1", 8388)


def test_method_is_lowercased():
    bean = parse(f"ss://{b64url('AES-256-GCM:pass')}@1.2.3.4:8388")
    assert bean.method == "aes-256-gcm"


def test_2022_plain_key_keeps_plus():
    """«+» в ключе не должен стать пробелом."""
    bean = parse(f"ss://2022-blake3-aes-256-gcm:{KEY_32}@1.2.3.4:8388#n")

    assert bean.method == "2022-blake3-aes-256-gcm"
    assert bean.password == KEY_32


def test_2022_percent_encoded_key_is_decoded():
    from urllib.parse import quote

    bean = parse(f"ss://2022-blake3-aes-256-gcm:{quote(KEY_32, safe='')}@1.2.3.4:8388#n")
    assert bean.password == KEY_32


def test_2022_base64_userinfo():
    bean = parse(f"ss://{b64url('2022-blake3-aes-128-gcm:' + KEY_16)}@1.2.3.4:8388")
    assert (bean.method, bean.password) == ("2022-blake3-aes-128-gcm", KEY_16)


def test_2022_multi_user_key():
    password = f"{KEY_32}:{KEY_32}"
    bean = parse(f"ss://2022-blake3-aes-256-gcm:{password}@1.2.3.4:8388")
    assert bean.password == password


@pytest.mark.parametrize(
    "password",
    [KEY_16, "not-base64!", f"{KEY_32}:{KEY_16}"],
    ids=["wrong-length", "not-base64", "second-key-wrong-length"],
)
def test_2022_broken_key_is_rejected(password):
    """Ядро на таком ключе отвергает весь конфиг («bad key»)."""
    assert parse_link(f"ss://2022-blake3-aes-256-gcm:{password}@1.2.3.4:8388") is None


@pytest.mark.parametrize(
    "link",
    [
        "ss://",
        "ss://@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm')}@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm:')}@1.2.3.4:8388",
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4",
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:port",
    ],
    ids=["empty", "no-userinfo", "no-password-part", "empty-password", "no-port", "bad-port"],
)
def test_malformed_links_are_rejected(link):
    assert parse_link(link) is None


def test_plugin_is_parsed():
    bean = parse(
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388/?plugin=obfs-local%3Bobfs%3Dhttp#n"
    )
    assert bean.plugin == "obfs-local;obfs=http"
    assert bean.server_port == 8388


@pytest.mark.parametrize("method", ["aes-256-cfb", "rc4-md5", "none", "plain"])
def test_unsupported_method_reports_build_error(method):
    bean = parse(f"ss://{b64url(method + ':pass')}@1.2.3.4:8388")

    result = bean.build_core_obj_xray()

    assert method in result["error"]
    assert result["outbound"] == {}


def test_plugin_reports_build_error():
    bean = parse(f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388?plugin=v2ray-plugin")
    assert "SIP003" in bean.build_core_obj_xray()["error"]


@pytest.mark.parametrize(
    "link",
    [
        f"ss://{b64url('aes-256-gcm:pass')}@1.2.3.4:8388#Name%20One",
        f"ss://2022-blake3-aes-256-gcm:{KEY_32}@example.com:443#n",
    ],
    ids=["aead", "2022"],
)
def test_share_link_roundtrip(link):
    original = parse(link)
    restored = parse(original.to_share_link())

    assert restored.method == original.method
    assert restored.password == original.password
    assert restored.server_address == original.server_address
    assert restored.server_port == original.server_port
    assert restored.name == original.name
