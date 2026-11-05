"""Первый неавторизованный обмен MTProto по HTTPS: порт TelegramProbe.kt.

Только req_pq: ни ключей, ни учётной записи, ни разложения. Это проверка пути по HTTPS, а не
родного транспорта приложения.
"""

from __future__ import annotations

import secrets
import struct
import time

from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget
from src.diag.models import DiagnosticFailure, ProbeObservation, ProbeRoute, ProbeStage, ProbeStatus
from src.diag.probes.https import address_problem, family_of
from src.diag.probes.support import (
    ProbeContext,
    TunnelEndpoint,
    classify,
    elapsed_since,
    https_exchange,
    status_of,
)

MAX_REPLY_BYTES = 4096
_REQ_PQ = 0xBE7E8EF1
_RES_PQ = 0x05162463
_VECTOR = 0x1CB5C415


def handshake_request(nonce: bytes, wall_time_ms: int) -> bytes:
    if len(nonce) != 16 or wall_time_ms <= 0:
        raise ValueError("bad handshake input")
    seconds, millis = divmod(wall_time_ms, 1000)
    message_id = ((seconds << 32) | (millis * (1 << 32) // 1000)) & ~3
    return struct.pack("<qQiI", 0, message_id, 20, _REQ_PQ) + nonce


def handshake_matches(data: bytes, nonce: bytes) -> bool:
    if len(nonce) != 16 or not 76 <= len(data) <= MAX_REPLY_BYTES:
        return False
    auth_key, message_id, length, constructor = struct.unpack_from("<qQiI", data, 0)
    if auth_key != 0 or not message_id & 1 or length != len(data) - 20:
        return False
    if constructor != _RES_PQ or data[24:40] != nonce:
        return False
    position = 56  # Серверный nonce временный и не сохраняется.
    pq_size = data[position]
    position += 1
    if not 1 <= pq_size <= 8 or len(data) - position < pq_size:
        return False
    pq = data[position : position + pq_size]
    if pq[0] == 0 or not pq[-1] & 1:
        return False
    position += pq_size
    padding = (4 - (pq_size + 1) % 4) % 4
    if len(data) - position < padding + 8 or any(data[position : position + padding]):
        return False
    position += padding
    vector, fingerprints = struct.unpack_from("<Ii", data, position)
    position += 8
    return (
        vector == _VECTOR and 1 <= fingerprints <= 64 and len(data) - position == fingerprints * 8
    )


def probe_telegram(
    context: ProbeContext,
    id: str,
    target: DiagnosticTarget,
    route: ProbeRoute,
    timeout: float,
    address: str | None = None,
    proxy: TunnelEndpoint | None = None,
) -> ProbeObservation:
    if target.purpose is not DiagnosticPurpose.TELEGRAM_APP or target.path not in ("/api", "/apiw"):
        raise ValueError("not a telegram target")
    started = time.monotonic()

    def result(status, failure=None, code=None, matched=False) -> ProbeObservation:
        return ProbeObservation(
            id, target.id, route, ProbeStage.HTTP, status,
            elapsed_ms=elapsed_since(started), failure_code=failure,
            address_family=family_of(address) if address else None, http_status=code,
            evidence={
                "coverage": "mtproto-first-exchange",
                "transport": "mtproto-https",
                "responseMatched": str(matched).lower(),
            },
        )  # fmt: skip

    problem = address_problem(address, target)
    if problem:
        return result(*problem)
    nonce = secrets.token_bytes(16)

    def read_limit(status, headers) -> int:
        length = headers.get("content-length", "")
        if status != 200 or (length.isdigit() and int(length) > MAX_REPLY_BYTES):
            return 0
        return MAX_REPLY_BYTES + 1

    try:
        response = https_exchange(
            context,
            hostname=target.hostname,
            path=target.path,
            address=address,
            proxy=proxy,
            method="POST",
            headers={
                "Accept-Encoding": "identity",
                "Cache-Control": "no-store",
                "Content-Type": "application/octet-stream",
            },
            body=handshake_request(nonce, int(time.time() * 1000)),
            timeout=timeout,
            read_limit=read_limit,
        )
    except (OSError, ValueError) as error:
        failure = classify(error, under_tun=context.under_tun)
        return result(status_of(failure), failure)
    code = response.status
    if 300 <= code <= 399:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code)
    if code != 200:
        failure = DiagnosticFailure.PROXY_AUTH if code == 407 else DiagnosticFailure.HTTP_REJECTED
        return result(ProbeStatus.FAILURE, failure, code)
    if not response.complete or len(response.body) > MAX_REPLY_BYTES:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.BODY_LIMIT, code)
    if handshake_matches(response.body, nonce):
        return result(ProbeStatus.SUCCESS, None, code, matched=True)
    return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code)
