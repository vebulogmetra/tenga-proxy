"""Ретраи загрузки и подписки в формате xray JSON (перенос из android 17b16bc, 5979aac)."""

import json
from unittest.mock import Mock, patch

import pytest
import requests

from src.fmt import parse_subscription_content
from src.sub.updater import SubscriptionUpdater


def _response(text: str) -> Mock:
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


# --- Ретраи ------------------------------------------------------------------


def test_fetch_retries_on_network_error_then_succeeds():
    updater = SubscriptionUpdater()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.time.sleep") as mock_sleep,
    ):
        mock_get.side_effect = [
            requests.ConnectionError("reset"),
            _response("ok content"),
        ]
        assert updater.fetch("http://example.com/sub") == "ok content"
        assert mock_get.call_count == 2
        # Пауза между попытками, чтобы не долбить сервер.
        assert mock_sleep.called


def test_fetch_gives_up_after_max_attempts():
    updater = SubscriptionUpdater()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.time.sleep"),
    ):
        mock_get.side_effect = requests.ConnectionError("reset")
        with pytest.raises(requests.ConnectionError):
            updater.fetch("http://example.com/sub")
        assert mock_get.call_count == SubscriptionUpdater.MAX_ATTEMPTS


def test_fetch_does_not_retry_on_http_error():
    """HTTP-код — окончательный ответ сервера, повтор лишь задержит UI."""
    updater = SubscriptionUpdater()

    response = Mock()
    response.raise_for_status = Mock(side_effect=requests.HTTPError("404"))

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.time.sleep"),
    ):
        mock_get.return_value = response
        with pytest.raises(requests.HTTPError):
            updater.fetch("http://example.com/sub")
        assert mock_get.call_count == 1


def test_fetch_succeeds_first_try_without_sleep():
    updater = SubscriptionUpdater()

    with (
        patch("src.sub.updater.requests.get") as mock_get,
        patch("src.sub.updater.time.sleep") as mock_sleep,
    ):
        mock_get.return_value = _response("content")
        assert updater.fetch("http://example.com/sub") == "content"
        assert mock_get.call_count == 1
        assert not mock_sleep.called


# --- Подписка в формате xray JSON --------------------------------------------


XRAY_CONFIG = {
    "outbounds": [
        {
            "protocol": "vless",
            "tag": "JsonNode",
            "settings": {
                "vnext": [
                    {
                        "address": "json.example.com",
                        "port": 443,
                        "users": [{"id": "11111111-1111-1111-1111-111111111111"}],
                    }
                ]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {"serverName": "json.example.com"},
                "wsSettings": {"path": "/ws"},
            },
        },
        # Служебные outbound'ы профилями не являются.
        {"protocol": "freedom", "tag": "direct"},
        {"protocol": "blackhole", "tag": "block"},
    ]
}


def test_parses_xray_json_config_subscription():
    beans = parse_subscription_content(json.dumps(XRAY_CONFIG))

    assert len(beans) == 1
    bean = beans[0]
    assert bean.proxy_type == "vless"
    assert bean.server_address == "json.example.com"
    assert bean.server_port == 443
    assert bean.stream.network == "ws"
    assert bean.stream.path == "/ws"
    assert bean.name == "JsonNode"


def test_parses_bare_outbounds_array():
    beans = parse_subscription_content(json.dumps(XRAY_CONFIG["outbounds"]))
    assert [b.proxy_type for b in beans] == ["vless"]


def test_json_subscription_does_not_break_plain_link_lists():
    content = "\n".join(
        [
            "vless://11111111-1111-1111-1111-111111111111@a.example.com:443?type=tcp#A",
            "trojan://secret@b.example.com:8443#B",
        ]
    )
    beans = parse_subscription_content(content)
    assert [b.proxy_type for b in beans] == ["vless", "trojan"]


def test_broken_json_falls_back_to_line_parsing():
    """Битый JSON не должен ронять разбор: подписка может быть просто списком."""
    content = "{not really json\nvless://11111111-1111-1111-1111-111111111111@a.example.com:443?type=tcp#A"
    beans = parse_subscription_content(content)
    assert [b.proxy_type for b in beans] == ["vless"]


def test_json_without_usable_outbounds_returns_empty():
    beans = parse_subscription_content(json.dumps({"outbounds": [{"protocol": "freedom"}]}))
    assert beans == []


# --- base64-детект ------------------------------------------------------------


def test_plain_link_list_is_not_mangled_by_base64_decode():
    """Список ссылок не должен «декодироваться» из base64 в мусор.

    decode_base64 работает с errors="ignore", поэтому на обычном тексте он не
    падает, а возвращает мусор — и подписка молча даёт 0 профилей. Срабатывало
    не всегда: зависит от того, кратна ли длина содержимого четырём.
    """
    content = "\n".join(
        [
            "vless://11111111-1111-1111-1111-111111111111@a.example.com:443?type=tcp#A",
            "trojan://secret@b.example.com:8443#B",
        ]
    )
    beans = parse_subscription_content(content)
    assert [b.proxy_type for b in beans] == ["vless", "trojan"]


def test_real_base64_subscription_still_decodes():
    import base64

    links = "\n".join(
        [
            "vless://11111111-1111-1111-1111-111111111111@a.example.com:443?type=tcp#A",
            "trojan://secret@b.example.com:8443#B",
        ]
    )
    encoded = base64.b64encode(links.encode()).decode()
    beans = parse_subscription_content(encoded)
    assert [b.proxy_type for b in beans] == ["vless", "trojan"]


def test_base64_of_xray_json_config_is_parsed():
    import base64

    encoded = base64.b64encode(json.dumps(XRAY_CONFIG).encode()).decode()
    beans = parse_subscription_content(encoded)
    assert [b.proxy_type for b in beans] == ["vless"]
