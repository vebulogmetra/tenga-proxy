"""Сообщения канала GUI ↔ служба: JSON по строкам."""

from __future__ import annotations

import pytest

from src.winsvc.protocol import (
    MAX_LINE,
    LineReader,
    ProtocolError,
    Request,
    Response,
    decode_request,
    decode_response,
    encode,
)


def test_request_roundtrip():
    request = Request(id=3, cmd="core.status", args={})

    assert decode_request(encode(request)) == request


def test_response_roundtrip():
    response = Response(id=3, ok=False, error="нет адаптера")

    assert decode_response(encode(response)) == response


def test_encoded_message_is_one_line():
    data = encode(Request(id=1, cmd="core.start", args={"config": {"a": "x\ny"}}))

    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1


def test_unknown_command_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":1,"id":1,"cmd":"shell.exec","args":{}}\n')


def test_other_version_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":2,"id":1,"cmd":"hello","args":{}}\n')


def test_garbage_is_rejected():
    with pytest.raises(ProtocolError):
        decode_request(b"not json\n")


def test_args_must_be_an_object():
    with pytest.raises(ProtocolError):
        decode_request(b'{"v":1,"id":1,"cmd":"hello","args":[]}\n')


def test_reader_splits_and_buffers_partial_lines():
    reader = LineReader()

    assert reader.feed(b'{"a":1}\n{"b"') == [b'{"a":1}']
    assert reader.feed(b":2}\n") == [b'{"b":2}']


def test_reader_refuses_oversized_line():
    reader = LineReader()

    with pytest.raises(ProtocolError):
        reader.feed(b"x" * (MAX_LINE + 1))
