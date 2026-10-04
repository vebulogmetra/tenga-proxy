"""Данные устройства в запросе подписки: только по явному согласию."""

import uuid
from unittest.mock import Mock, patch

from src.db.data_store import DataStore
from src.sub.device import DeviceInfo, device_headers, ensure_hwid, read_device_info
from src.sub.updater import SubscriptionUpdater

INFO = DeviceInfo(os_version="Ubuntu 26.04", model="ThinkPad X1", language="ru-RU")


def _enabled() -> DataStore:
    config = DataStore()
    config.sub_send_device_info = True
    ensure_hwid(config)
    return config


def test_nothing_is_sent_by_default():
    config = DataStore()

    assert device_headers(config, INFO) == {}
    # Без согласия идентификатор не должен даже появляться.
    assert config.sub_hwid == ""


def test_hwid_is_created_once_and_stays_the_same():
    config = DataStore()

    first = ensure_hwid(config)
    second = ensure_hwid(config)

    assert first == second == config.sub_hwid
    assert str(uuid.UUID(first)) == first


def test_enabled_flag_sends_the_device_headers():
    config = _enabled()

    assert device_headers(config, INFO) == {
        "x-hwid": config.sub_hwid,
        "x-device-os": "Linux",
        "x-ver-os": "Ubuntu 26.04",
        "x-device-model": "ThinkPad X1",
        "Accept-Language": "ru-RU",
    }


def test_no_headers_without_a_stored_hwid():
    """Несохранённый идентификатор менялся бы при каждом запуске — «новое устройство»."""
    config = DataStore()
    config.sub_send_device_info = True

    assert device_headers(config, INFO) == {}


def test_header_values_are_printable_ascii():
    """requests отказывается отправлять заголовок с не-latin-1 символами."""
    config = _enabled()
    info = DeviceInfo(os_version="Альт 11", model="Ноутбук\r\nX: 1", language="")

    headers = device_headers(config, info)

    assert headers["x-ver-os"] == "11"
    assert headers["x-device-model"] == "X: 1"
    assert "Accept-Language" not in headers


def test_hwid_is_hidden_from_repr():
    """repr настроек попадает в журнал при отладке."""
    config = _enabled()

    assert config.sub_hwid not in repr(config)


def test_hwid_survives_saving_and_loading(tmp_path):
    config = _enabled()
    config.save(tmp_path / "settings.json")

    assert DataStore.load(tmp_path / "settings.json").sub_hwid == config.sub_hwid


def test_real_device_info_is_readable():
    info = read_device_info()

    assert info.os_version
    assert info.model


def _ok() -> Mock:
    response = Mock()
    response.text = "ok"
    response.raise_for_status = Mock()
    return response


def test_updater_adds_device_headers_when_enabled():
    config = _enabled()

    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(config=config).fetch("https://example.com/sub")

    sent = mock_get.call_args.kwargs["headers"]
    assert sent["x-hwid"] == config.sub_hwid
    assert sent["x-device-os"] == "Linux"
    assert sent["User-Agent"]


def test_updater_sends_no_device_headers_by_default():
    with patch("src.sub.updater.requests.get", return_value=_ok()) as mock_get:
        SubscriptionUpdater(config=DataStore()).fetch("https://example.com/sub")

    assert set(mock_get.call_args.kwargs["headers"]) == {"User-Agent"}
