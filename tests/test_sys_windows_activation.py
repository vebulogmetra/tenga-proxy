"""Передача активации от второго экземпляра первому."""

from __future__ import annotations

import threading
import time

from src.sys.windows.activation import ActivationServer, pipe_address, send_activation


def test_address_is_a_named_pipe_per_user_and_config():
    first = pipe_address("C:/a/x.lock", user="alice")
    second = pipe_address("C:/b/x.lock", user="alice")

    assert first.startswith("\\\\.\\pipe\\ru.tenga.Proxy-")
    assert first != second


def test_second_instance_delivers_uris(tmp_path):
    address = str(tmp_path / "activate.sock")
    got = []
    done = threading.Event()

    def on_request(uris):
        got.append(uris)
        done.set()

    server = ActivationServer(address, on_request, family="AF_UNIX")
    server.start()
    try:
        assert send_activation(address, ["veblock://add/x"], family="AF_UNIX") is True
        assert done.wait(5)
    finally:
        server.stop()

    assert got == [["veblock://add/x"]]


def test_send_without_server_reports_failure(tmp_path):
    assert send_activation(str(tmp_path / "none.sock"), [], family="AF_UNIX") is False


def test_garbage_request_is_ignored(tmp_path):
    from multiprocessing.connection import Client

    address = str(tmp_path / "activate.sock")
    got = []
    server = ActivationServer(address, got.append, family="AF_UNIX")
    server.start()
    try:
        with Client(address, family="AF_UNIX", authkey=b"tenga-activate") as conn:
            conn.send({"uris": "not-a-list"})
        # Второй, нормальный запрос доказывает, что поток сервера жив.
        assert send_activation(address, [], family="AF_UNIX") is True
        time.sleep(0.2)
    finally:
        server.stop()

    # Мусор превращается в пустой список, а не доходит до обработчика как есть.
    assert got == [[], []]
