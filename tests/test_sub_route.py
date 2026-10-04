"""Маршрут загрузки подписки: сначала через работающий прокси, потом напрямую."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.core.context import ProxyState
from src.db.config import ProxyMode
from src.db.data_store import DataStore
from src.sub.errors import MAX_RESPONSE_SIZE, SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.route import local_proxy_url
from src.sub.updater import SubscriptionUpdater

PROXY = "http://127.0.0.1:2081"
URL = "https://provider.example/sub/secret-token"


def _ok(text: str = "ok") -> Mock:
    response = Mock()
    response.text = text
    response.raise_for_status = Mock()
    return response


def _http_error(status: int, body: str = "") -> Mock:
    response = Mock()
    response.status_code = status
    response.text = body
    response.raise_for_status = Mock(side_effect=requests.HTTPError(str(status)))
    return response


def _via_proxy(call) -> bool:
    return "proxies" in call.kwargs


# --- когда есть через что качать ----------------------------------------------


def _state(running: bool, mode: str) -> ProxyState:
    state = ProxyState()
    if running:
        state.set_running(1, mode=mode)
    return state


def test_no_local_proxy_while_disconnected():
    assert local_proxy_url(DataStore(), _state(False, ProxyMode.SYSTEM_PROXY)) is None


def test_no_local_proxy_in_tun_mode():
    """В TUN запросы приложения и так идут через туннель, а HTTP-inbound не поднят."""
    assert local_proxy_url(DataStore(), _state(True, ProxyMode.TUN)) is None


def test_local_proxy_is_the_http_inbound_next_to_socks():
    assert local_proxy_url(DataStore(), _state(True, ProxyMode.SYSTEM_PROXY)) == PROXY


def test_local_proxy_follows_the_configured_address_and_port():
    config = DataStore(inbound_address="127.0.0.2", inbound_socks_port=3000)

    assert local_proxy_url(config, _state(True, ProxyMode.SYSTEM_PROXY)) == "http://127.0.0.2:3001"


@pytest.mark.parametrize("address", ["0.0.0.0", "::", ""])
def test_wildcard_listen_address_is_reached_through_loopback(address):
    config = DataStore(inbound_address=address)

    assert local_proxy_url(config, _state(True, ProxyMode.SYSTEM_PROXY)) == PROXY


# --- порядок маршрутов --------------------------------------------------------


def test_without_a_proxy_the_request_goes_directly():
    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(proxy_url=lambda: None).fetch(URL)

    assert mock_get.call_count == 1
    assert not _via_proxy(mock_get.call_args)


def test_a_connected_proxy_is_tried_first():
    with patch("src.sub.updater.requests.get", return_value=_ok("via proxy")) as mock_get:
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "via proxy"
    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs["proxies"] == {"http": PROXY, "https": PROXY}


def test_network_failure_through_the_proxy_falls_back_to_direct():
    def get(_url, **kwargs):
        if "proxies" in kwargs:
            raise requests.ConnectionError("proxy is dead")
        return _ok("direct")

    with (
        patch("src.sub.updater.requests.get", side_effect=get) as mock_get,
        patch("src.sub.updater.time.sleep"),
    ):
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "direct"
    routes = [_via_proxy(call) for call in mock_get.call_args_list]
    assert routes == [True] * SubscriptionUpdater.MAX_ATTEMPTS + [False]


def test_http_error_through_the_proxy_is_not_final():
    """Провайдер может не отдавать подписку адресу выхода прокси (403 по стране)."""
    with patch("src.sub.updater.requests.get") as mock_get:
        mock_get.side_effect = [_http_error(403, "country code: US"), _ok("direct")]
        result = SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert result == "direct"
    assert [_via_proxy(call) for call in mock_get.call_args_list] == [True, False]


def test_the_servers_answer_beats_a_dropped_direct_connection():
    """Ответ сервера через прокси объясняет больше, чем обрыв напрямую."""

    def get(_url, **kwargs):
        if "proxies" in kwargs:
            return _http_error(403, "Device limit reached")
        raise requests.ConnectionError("blocked")

    with (
        patch("src.sub.updater.requests.get", side_effect=get),
        patch("src.sub.updater.time.sleep"),
        pytest.raises(SubscriptionHttpError) as caught,
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caught.value.body_snippet == "Device limit reached"


def test_two_http_errors_report_the_direct_one():
    answers = [_http_error(403), _http_error(404)]
    with (
        patch("src.sub.updater.requests.get", side_effect=answers),
        pytest.raises(SubscriptionHttpError) as caught,
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caught.value.status_code == 404


def test_an_oversized_response_through_the_proxy_is_final():
    huge = _ok("x" * (MAX_RESPONSE_SIZE + 1))
    with (
        patch("src.sub.updater.requests.get", return_value=huge) as mock_get,
        pytest.raises(SubscriptionTooLargeError),
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert mock_get.call_count == 1


def test_the_subscription_address_never_reaches_the_log(caplog):
    """В адресе — токен пользователя, а текст ошибок requests содержит URL целиком."""

    def get(url, **kwargs):
        if "proxies" in kwargs:
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
        return _ok()

    with (
        patch("src.sub.updater.requests.get", side_effect=get),
        patch("src.sub.updater.time.sleep"),
        caplog.at_level("DEBUG", logger="tenga.sub.updater"),
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)

    assert caplog.records
    assert "secret-token" not in caplog.text


# --- настройки ----------------------------------------------------------------


def test_the_dead_sub_use_proxy_setting_is_gone():
    """Поле осталось от NekoRay и нигде не читалось: маршрут выбирается сам."""
    assert not hasattr(DataStore(), "sub_use_proxy")
    assert DataStore.from_dict({"sub_use_proxy": False, "inbound_socks_port": 3000}) == DataStore(
        inbound_socks_port=3000
    )


def test_local_ipv6_proxy_has_brackets_in_the_url():
    config = DataStore(inbound_address="::1")
    assert local_proxy_url(config, _state(True, ProxyMode.SYSTEM_PROXY)) == "http://[::1]:2081"


def test_an_oversized_direct_answer_is_not_hidden_by_a_proxy_http_error():
    with (
        patch(
            "src.sub.updater.requests.get",
            side_effect=[_http_error(403), _ok("x" * (MAX_RESPONSE_SIZE + 1))],
        ),
        pytest.raises(SubscriptionTooLargeError),
    ):
        SubscriptionUpdater(proxy_url=lambda: PROXY).fetch(URL)
