"""Обслуживание одного подключения поверх произвольного канала."""

from __future__ import annotations

from src.winsvc.protocol import Request, decode_response, encode
from src.winsvc.server import serve_connection


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
