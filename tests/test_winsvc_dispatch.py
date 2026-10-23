"""Диспетчер: запрос → метод состояния → ответ, ошибки — в текст."""

from __future__ import annotations

from src.winsvc.dispatch import dispatch
from src.winsvc.protocol import Request
from src.winsvc.state import ServiceError


class FakeState:
    def core_status(self):
        return {"running": True}

    def routes_apply(self, tun_name, proxy_host):
        return {"proxy_ip": proxy_host}

    def core_stop(self):
        raise ServiceError("уже остановлено")

    def core_stats(self):
        raise RuntimeError("bug")


def test_call_with_args():
    response = dispatch(
        FakeState(), Request(1, "routes.apply", {"tun_name": "xray0", "proxy_host": "h"})
    )

    assert response.ok and response.result == {"proxy_ip": "h"}


def test_service_error_text_is_returned():
    response = dispatch(FakeState(), Request(2, "core.stop", {}))

    assert (response.ok, response.error) == (False, "уже остановлено")


def test_unexpected_error_is_hidden():
    response = dispatch(FakeState(), Request(3, "core.stats", {}))

    assert not response.ok
    assert "bug" not in response.error


def test_missing_args_are_an_error():
    response = dispatch(FakeState(), Request(4, "routes.apply", {"tun_name": "xray0"}))

    assert not response.ok
