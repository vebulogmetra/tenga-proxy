"""Канал GUI ↔ служба: одна JSON-строка на сообщение.

Запрос `{"v":1,"id":N,"cmd":"…","args":{…}}`, ответ
`{"v":1,"id":N,"ok":true,"result":{…}}` или `{"v":1,"id":N,"ok":false,"error":"…"}`.
Служба сама ничего не присылает: синхронный pipe не даёт читать и писать
одновременно, поэтому события (лог ядра, его выход) приходят в ответе на
`core.status`. Модуль не зависит от Windows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
# Конфиг сессии — десятки килобайт; мегабайты означают ошибку или атаку.
MAX_LINE = 4 * 1024 * 1024

COMMANDS = frozenset(
    {
        "hello",
        "core.start",
        "core.stop",
        "core.status",
        "core.stats",
        "routes.apply",
        "routes.restore",
        "dns.apply",
        "wireguard.up",
        "wireguard.down",
    }
)


class ProtocolError(ValueError):
    """Сообщение не соответствует протоколу."""


@dataclass(frozen=True)
class Request:
    id: int
    cmd: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    id: int
    ok: bool
    result: dict = field(default_factory=dict)
    error: str = ""


def encode(message: Request | Response) -> bytes:
    if isinstance(message, Request):
        payload = {
            "v": PROTOCOL_VERSION,
            "id": message.id,
            "cmd": message.cmd,
            "args": message.args,
        }
    else:
        payload = {"v": PROTOCOL_VERSION, "id": message.id, "ok": message.ok}
        if message.ok:
            payload["result"] = message.result
        else:
            payload["error"] = message.error
    # ensure_ascii: перевод строки внутри значения экранируется, сообщение — одна строка.
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def _load(line: bytes) -> dict:
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ProtocolError(f"not JSON: {e}") from e
    if not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    if not isinstance(data.get("id"), int):
        raise ProtocolError("missing id")
    return data


def decode_request(line: bytes) -> Request:
    data = _load(line)
    cmd = data.get("cmd")
    if cmd not in COMMANDS:
        raise ProtocolError(f"unknown command: {cmd!r}")
    args = data.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("args must be an object")
    return Request(id=data["id"], cmd=cmd, args=args)


def decode_response(line: bytes) -> Response:
    data = _load(line)
    ok = data.get("ok")
    if not isinstance(ok, bool):
        raise ProtocolError("missing ok")
    result = data.get("result", {})
    return Response(
        id=data["id"],
        ok=ok,
        result=result if isinstance(result, dict) else {},
        error=str(data.get("error", "")),
    )


class LineReader:
    """Режет поток байтов на строки, не давая буферу расти без предела."""

    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b"\n")
        if len(self._buffer) > MAX_LINE or any(len(line) > MAX_LINE for line in lines):
            raise ProtocolError("line too long")
        return [line for line in lines if line.strip()]
