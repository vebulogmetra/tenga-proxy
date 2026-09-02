"""XHTTP extra params from share links (port of android 1629dbd)."""

import json

from src.fmt.protocols import TrojanBean, VLESSBean
from src.fmt.stream import StreamSettings

EXTRA = (
    '{"scMaxEachPostBytes":1000000,"scMinPostsIntervalMs":30,'
    '"xmux":{"maxConcurrency":"16-32"},"seqKey":"abc"}'
)


def test_stream_defaults_have_empty_xhttp_fields():
    stream = StreamSettings()
    assert stream.xhttp_extra == ""
    assert stream.xhttp_mode == ""
    assert stream.xhttp_padding_bytes == ""


def test_build_transport_xhttp_uses_extra_as_base():
    stream = StreamSettings(network="xhttp", path="/p", xhttp_extra=EXTRA)
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["scMaxEachPostBytes"] == 1000000
    assert settings["xmux"] == {"maxConcurrency": "16-32"}
    assert settings["seqKey"] == "abc"
    assert settings["path"] == "/p"


def test_explicit_link_params_override_extra():
    extra = json.dumps({"mode": "packet-up", "path": "/from-extra"})
    stream = StreamSettings(
        network="xhttp", path="/explicit", xhttp_mode="stream-one", xhttp_extra=extra
    )
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["mode"] == "stream-one"
    assert settings["path"] == "/explicit"


def test_extra_supplies_defaults_when_link_has_no_explicit_values():
    extra = json.dumps({"mode": "packet-up", "path": "/from-extra"})
    stream = StreamSettings(network="xhttp", xhttp_extra=extra)
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["mode"] == "packet-up"
    assert settings["path"] == "/from-extra"


def test_padding_bytes_reaches_settings():
    stream = StreamSettings(network="xhttp", xhttp_padding_bytes="100-1000")
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["xPaddingBytes"] == "100-1000"


def test_broken_extra_is_ignored_not_fatal():
    stream = StreamSettings(network="xhttp", path="/p", xhttp_extra="{not json")
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["path"] == "/p"


def test_non_object_extra_is_ignored():
    stream = StreamSettings(network="xhttp", path="/p", xhttp_extra="[1,2,3]")
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["path"] == "/p"


def test_vless_parses_extra_from_link():
    from urllib.parse import quote

    link = f"vless://uuid-1@example.com:443?type=xhttp&security=tls&mode=stream-one&xPaddingBytes=100-1000&extra={quote(EXTRA)}"
    bean = VLESSBean()
    assert bean.try_parse_link(link) is True
    assert json.loads(bean.stream.xhttp_extra)["seqKey"] == "abc"
    assert bean.stream.xhttp_mode == "stream-one"
    assert bean.stream.xhttp_padding_bytes == "100-1000"


def test_vless_broken_extra_does_not_break_parsing():
    link = "vless://uuid-1@example.com:443?type=xhttp&security=tls&extra=%7Bnot+json"
    bean = VLESSBean()
    assert bean.try_parse_link(link) is True
    assert bean.stream.xhttp_extra == ""


def test_vless_share_link_roundtrip_preserves_extra():
    from urllib.parse import quote

    link = f"vless://uuid-1@example.com:443?type=xhttp&security=tls&mode=stream-one&xPaddingBytes=100-1000&extra={quote(EXTRA)}"
    bean = VLESSBean()
    bean.try_parse_link(link)

    restored = VLESSBean()
    assert restored.try_parse_link(bean.to_share_link()) is True
    assert json.loads(restored.stream.xhttp_extra) == json.loads(EXTRA)
    assert restored.stream.xhttp_mode == "stream-one"
    assert restored.stream.xhttp_padding_bytes == "100-1000"


def test_trojan_parses_and_roundtrips_extra():
    from urllib.parse import quote

    link = (
        f"trojan://pass@example.com:443?type=xhttp&security=tls&mode=packet-up&extra={quote(EXTRA)}"
    )
    bean = TrojanBean()
    assert bean.try_parse_link(link) is True
    assert json.loads(bean.stream.xhttp_extra)["seqKey"] == "abc"

    restored = TrojanBean()
    assert restored.try_parse_link(bean.to_share_link()) is True
    assert json.loads(restored.stream.xhttp_extra) == json.loads(EXTRA)
    assert restored.stream.xhttp_mode == "packet-up"
