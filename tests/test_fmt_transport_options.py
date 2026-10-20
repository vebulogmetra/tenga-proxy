"""Untrusted transport JSON must not change socket or destination policy."""

import json

import pytest

from src.fmt.protocols import Hysteria2Bean
from src.fmt.stream import StreamSettings


def xhttp(value):
    return StreamSettings(network="xhttp", xhttp_extra=json.dumps(value)).build_transport()[
        "splithttpSettings"
    ]


def test_xhttp_filters_nested_socket_and_destination_options():
    assert xhttp(
        {
            "seqKey": "ok",
            "xmux": {"maxConcurrency": "2-4", "sockopt": {}},
            "downloadSettings": {"address": "127.0.0.1", "port": 22},
            "extra": {"seqKey": "nested", "sockopt": {"mark": 42}},
        }
    ) == {"seqKey": "ok", "xmux": {"maxConcurrency": "2-4"}, "extra": {"seqKey": "nested"}}


@pytest.mark.parametrize("value", [True, {}, [], None])
def test_xhttp_rejects_wrong_range_type(value):
    with pytest.raises(ValueError, match="scMaxEachPostBytes"):
        xhttp({"scMaxEachPostBytes": value})


def test_extra_depth_is_bounded():
    value = {"seqKey": "ok"}
    for _ in range(20):
        value = {"extra": value}
    with pytest.raises(ValueError, match="вложен"):
        xhttp(value)


def test_finalmask_filters_nested_options_and_preserves_supported_obfuscation():
    bean = Hysteria2Bean(auth="test", server_address="example.com")
    bean.final_mask = json.dumps(
        {
            "udp": [
                {"type": "salamander", "settings": {"password": "test", "sockopt": {}}},
                {
                    "type": "udphop",
                    "settings": {
                        "interval": "30",
                        "remotePorts": "443",
                        "remoteIPs": ["127.0.0.1"],
                        "sockopt": {},
                    },
                },
                {"type": "realm", "settings": {"url": "realm://secret@localhost/id"}},
            ],
            "quicParams": {"congestion": "brutal", "brutalUp": "10 mbps", "tlsSettings": {}},
        }
    )
    mask = bean.build_outbound()["streamSettings"]["finalmask"]
    assert mask == {
        "udp": [
            {"type": "udphop", "settings": {"interval": "30", "remotePorts": "443"}},
            {"type": "salamander", "settings": {"password": "test"}},
        ],
        "quicParams": {"congestion": "brutal", "brutalUp": "10 mbps"},
    }


def test_warning_does_not_include_discarded_value(caplog):
    xhttp({"sockopt": {"secret": "never-log-me"}})
    assert "sockopt" in caplog.text
    assert "never-log-me" not in caplog.text


def test_explicit_padding_overrides_nested_extra():
    stream = StreamSettings(
        network="xhttp",
        xhttp_padding_bytes="100-200",
        xhttp_extra='{"extra":{"xPaddingBytes":"300-400"}}',
    )
    settings = stream.build_transport()["splithttpSettings"]
    assert settings["extra"]["xPaddingBytes"] == "100-200"


def test_noise_and_custom_headers_are_filtered_recursively():
    from src.fmt.transport_options import filter_finalmask_options

    value = {
        "udp": [
            {
                "type": "noise",
                "settings": {"noise": [{"packet": "hello", "type": "str", "sockopt": {"mark": 1}}]},
            },
            {
                "type": "header-custom",
                "settings": {"client": [{"packet": [1, 2], "dialerProxy": "evil"}]},
            },
        ]
    }
    assert filter_finalmask_options(value) == {
        "udp": [
            {"type": "noise", "settings": {"noise": [{"packet": "hello", "type": "str"}]}},
            {"type": "header-custom", "settings": {"client": [{"packet": [1, 2]}]}},
        ]
    }
