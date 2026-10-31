"""Клиент канала службы поверх socketpair и настоящего serve_connection."""

from __future__ import annotations

import socket
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src import __version__
from src.sys.windows.service_client import ServiceClient, ServiceUnavailable, _start_service
from src.winsvc.server import serve_connection
from src.winsvc.state import ServiceError


class SocketChannel:
    def __init__(self, sock):
        self.sock = sock

    def read(self):
        return self.sock.recv(65536)

    def write(self, data):
        self.sock.sendall(data)

    def close(self):
        self.sock.close()


class FakeState:
    def client_connected(self):
        pass

    def client_gone(self):
        pass

    def hello(self, version):
        if version != __version__:
            raise ServiceError("версия")
        return {"version": version}

    def core_status(self):
        return {"running": True, "exited": False, "log": ["a"]}

    def core_stop(self):
        raise ServiceError("нечего останавливать")


@pytest.fixture
def client():
    server_sock, client_sock = socket.socketpair()
    thread = threading.Thread(
        target=serve_connection, args=(SocketChannel(server_sock), FakeState()), daemon=True
    )
    thread.start()
    result = ServiceClient(opener=lambda: SocketChannel(client_sock), starter=lambda: None)
    yield result
    result.close()


def test_call_returns_result(client):
    assert client.call("core.status")["log"] == ["a"]


def test_service_error_is_raised_with_text(client):
    with pytest.raises(ServiceError, match="нечего"):
        client.call("core.stop")


def test_unavailable_service_is_reported(caplog):
    def opener():
        raise OSError("pipe not found")

    broken = ServiceClient(opener=opener, starter=lambda: None, connect_timeout=0.2)

    with pytest.raises(ServiceUnavailable):
        broken.call("core.status")
    assert "Cannot open Veblock service pipe: pipe not found" in caplog.text


def test_start_service_requests_only_connect_and_start_permissions(monkeypatch):
    api = SimpleNamespace(
        SC_MANAGER_CONNECT=1,
        SERVICE_START=16,
        OpenSCManager=Mock(return_value="scm"),
        OpenService=Mock(return_value="service"),
        StartService=Mock(),
        CloseServiceHandle=Mock(),
    )
    monkeypatch.setitem(sys.modules, "win32service", api)

    _start_service()

    api.OpenSCManager.assert_called_once_with(None, None, 1)
    api.OpenService.assert_called_once_with("scm", "TengaProxySvc", 16)
    api.StartService.assert_called_once_with("service", None)
    assert [call.args for call in api.CloseServiceHandle.call_args_list] == [
        ("service",),
        ("scm",),
    ]
