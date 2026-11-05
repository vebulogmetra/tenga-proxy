"""HTTPS-проба: порт HttpsProbe.kt. Редиректы только фиксируются, тело из пробы не выходит."""

from __future__ import annotations

import re
import time

from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget, is_public_address
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.probes.support import (
    ProbeContext,
    TunnelEndpoint,
    classify,
    elapsed_since,
    https_exchange,
    status_of,
)

_WEB_ENTRY = frozenset(
    {
        DiagnosticPurpose.INSTAGRAM_WEB,
        DiagnosticPurpose.TELEGRAM_WEB,
        DiagnosticPurpose.YOUTUBE_WEB,
    }
)
_INSPECT_CHALLENGE = frozenset(
    {
        DiagnosticPurpose.INSTAGRAM_WEB,
        DiagnosticPurpose.YOUTUBE_WEB,
        DiagnosticPurpose.BASELINE,
    }
)
_CHALLENGE_MARKS = (
    "challenge_required",
    "checkpoint_required",
    "cf-chl-",
    "enable javascript and cookies",
)
_ROBOTS = re.compile(r"(?m)^user-agent\s*:")
WEB_ENTRY_BYTES = 4096
_CHALLENGE_PREFIX = 4096


def family_of(address: str) -> AddressFamily:
    return AddressFamily.IPV6 if ":" in address else AddressFamily.IPV4


def address_problem(address: str | None, target: DiagnosticTarget):
    """Статус и код, если на адрес идти нельзя: проверяется прямо перед соединением."""
    if address is None:
        return None
    if family_of(address) not in target.families:
        return ProbeStatus.UNSUPPORTED, None
    if not is_public_address(address):
        return ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNSAFE_ADDRESS
    return None


def probe_https(
    context: ProbeContext,
    id: str,
    target: DiagnosticTarget,
    route: ProbeRoute,
    timeout: float,
    address: str | None = None,
    proxy: TunnelEndpoint | None = None,
) -> ProbeObservation:
    started = time.monotonic()
    family = family_of(address) if address else None

    def result(status, failure=None, code=None, evidence=None) -> ProbeObservation:
        return ProbeObservation(
            id, target.id, route, ProbeStage.HTTP, status,
            elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
            http_status=code, evidence=evidence or {},
        )  # fmt: skip

    problem = address_problem(address, target)
    if problem:
        return result(*problem)
    web_entry = target.expected_body is None and target.purpose in _WEB_ENTRY

    def read_limit(status, headers) -> int:
        if not 200 <= status <= 299:
            return 0
        if web_entry:
            return min(target.max_bytes, WEB_ENTRY_BYTES)
        length = headers.get("content-length", "")
        # Лишнее не качаем: слишком большое тело само по себе уже итог пробы.
        return 0 if length.isdigit() and int(length) > target.max_bytes else target.max_bytes

    try:
        response = https_exchange(
            context,
            hostname=target.hostname,
            path=target.path,
            address=address,
            proxy=proxy,
            port=target.port,
            headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"},
            timeout=timeout,
            read_limit=read_limit,
        )
    except (OSError, ValueError) as error:
        failure = classify(error, under_tun=context.under_tun)
        timings = getattr(error, "timings", {})
        return result(status_of(failure), failure, evidence={**timings, "transport": "https"})
    return _judge(target, response, result, web_entry)


def _judge(target, response, result, web_entry) -> ProbeObservation:
    code = response.status
    timings = {k: v for k, v in response.timings.items() if k != "bodyMs"}
    evidence = {**timings, "transport": "https"}
    if response.tls_version:
        evidence["tlsVersion"] = response.tls_version
    if 300 <= code <= 399:
        return result(
            ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code, evidence
        )
    if not 200 <= code <= 299:
        failure = DiagnosticFailure.PROXY_AUTH if code == 407 else DiagnosticFailure.HTTP_REJECTED
        return result(ProbeStatus.FAILURE, failure, code, evidence)
    body = response.body
    evidence["receivedBytes"] = str(len(body))
    evidence["bodyMs"] = response.timings.get("bodyMs", "0")
    if not response.complete and not web_entry:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.BODY_LIMIT, code, evidence)
    if web_entry:
        evidence["coverage"] = "web-entry-only"
    prefix = None
    if target.purpose in _INSPECT_CHALLENGE:
        prefix = body[:_CHALLENGE_PREFIX].decode("utf-8", "replace").lower()
    if prefix is not None and any(mark in prefix for mark in _CHALLENGE_MARKS):
        evidence["coverage"] = "web-challenge"
        evidence["responseMatched"] = "false"
        return result(
            ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code, evidence
        )
    if target.purpose is DiagnosticPurpose.INSTAGRAM_MEDIA:
        evidence["coverage"] = "public-static-only"
        is_webp = (
            len(body) >= 12
            and body[:4] == b"RIFF"
            and body[8:12] == b"WEBP"
            and response.content_type.split(";")[0].strip().lower() == "image/webp"
        )
        if not is_webp:
            return result(
                ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code, evidence
            )
    if target.coverage == "robots-response" and (prefix is None or not _ROBOTS.search(prefix)):
        evidence["responseMatched"] = "false"
        return result(
            ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code, evidence
        )
    matched = (target.expected_status is None or code == target.expected_status) and (
        target.expected_body is None or body == target.expected_body.encode("utf-8")
    )
    evidence["responseMatched"] = str(matched).lower()
    if matched:
        return result(ProbeStatus.SUCCESS, None, code, evidence)
    return result(ProbeStatus.FAILURE, DiagnosticFailure.UNEXPECTED_RESPONSE, code, evidence)
