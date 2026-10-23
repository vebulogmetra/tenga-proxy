"""Передача активации от второго экземпляра первому."""

from __future__ import annotations

import sys
import threading
import time
import uuid

import pytest

from src.sys.windows.activation import ActivationServer, pipe_address, send_activation

# Протокол один и тот же; на Windows проверяется настоящий named pipe, на
# Linux — сокет AF_UNIX того же multiprocessing.connection.
FAMILY = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"


@pytest.fixture
def address(tmp_path):
    if FAMILY == "AF_PIPE":
        return f"\\\\.\\pipe\\tenga-test-{uuid.uuid4().hex}"
    return str(tmp_path / "activate.sock")


def test_address_is_a_named_pipe_per_user_and_config():
    first = pipe_address("C:/a/x.lock", user="alice")
    second = pipe_address("C:/b/x.lock", user="alice")

    assert first.startswith("\\\\.\\pipe\\ru.tenga.Proxy-")
    assert first != second


def test_second_instance_delivers_uris(address):
    got = []
    done = threading.Event()

    def on_request(uris):
        got.append(uris)
        done.set()

    server = ActivationServer(address, on_request, family=FAMILY)
    server.start()
    try:
        assert send_activation(address, ["veblock://add/x"], family=FAMILY) is True
        assert done.wait(5)
    finally:
        server.stop()

    assert got == [["veblock://add/x"]]


def test_send_without_server_reports_failure(address):
    assert send_activation(address, [], family=FAMILY) is False


def test_garbage_request_is_ignored(address):
    from multiprocessing.connection import Client

    got = []
    server = ActivationServer(address, got.append, family=FAMILY)
    server.start()
    try:
        with Client(address, family=FAMILY, authkey=b"tenga-activate") as conn:
            conn.send({"uris": "not-a-list"})
        # Второй, нормальный запрос доказывает, что поток сервера жив.
        assert send_activation(address, [], family=FAMILY) is True
        time.sleep(0.2)
    finally:
        server.stop()

    # Мусор превращается в пустой список, а не доходит до обработчика как есть.
    assert got == [[], []]
