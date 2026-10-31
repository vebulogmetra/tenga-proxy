"""Обслуживание одного подключения поверх произвольного канала."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.winsvc.protocol import Request, decode_response, encode
from src.winsvc.server import PipeServer, serve_connection


class FakeChannel:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = b""

    def read(self) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data: bytes) -> None:
        self.written += data


class FakeState:
    def __init__(self):
        self.events = []

    def client_connected(self):
        self.events.append("connected")

    def client_gone(self):
        self.events.append("gone")

    def core_status(self):
        return {"running": False}


def test_requests_are_answered_and_presence_tracked():
    data = encode(Request(1, "core.status", {}))
    channel = FakeChannel([data[:5], data[5:]])
    state = FakeState()

    serve_connection(channel, state)

    assert decode_response(channel.written.strip()).result == {"running": False}
    assert state.events == ["connected", "gone"]


def test_protocol_violation_closes_connection():
    channel = FakeChannel([b"garbage\n", encode(Request(2, "core.status", {}))])
    state = FakeState()

    serve_connection(channel, state)

    assert b'"ok":false' in channel.written
    assert state.events == ["connected", "gone"]


@pytest.mark.parametrize("failure", ["connect", "session"])
def test_pipe_accepts_next_client_after_failure(monkeypatch, caplog, failure):
    class PipeError(Exception):
        winerror = 232  # ERROR_NO_DATA: клиент закрыл канал до ConnectNamedPipe.

    server = PipeServer(FakeState())
    handles = iter(["failed", "next"])
    monkeypatch.setattr(server, "_create", lambda: next(handles))
    monkeypatch.setattr("src.winsvc.server.RETRY_SECONDS", 0)
    closed = []

    def connect(handle, unused):
        if handle == "failed" and failure == "connect":
            raise PipeError("client already disconnected")

    served = []

    def serve(channel, state):
        served.append(channel._handle)
        if channel._handle == "failed":
            raise RuntimeError("session failed")
        server._stopping.set()

    monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=PipeError))
    monkeypatch.setitem(sys.modules, "win32file", SimpleNamespace(CloseHandle=closed.append))
    monkeypatch.setitem(
        sys.modules,
        "win32pipe",
        SimpleNamespace(ConnectNamedPipe=connect, DisconnectNamedPipe=Mock()),
    )
    monkeypatch.setattr("src.winsvc.server.serve_connection", serve)

    server.serve_forever()

    assert served[-1] == "next"
    assert closed == ["failed", "next"]
    assert "Service pipe session failed" in caplog.text
