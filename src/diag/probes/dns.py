"""Системный DNS, DoH и проверки транспорта DNS: порт SystemDnsProbe, DohProbe, DnsTransportProbe.

Настоящие серверы сети опрашиваются напрямую: getaddrinfo под TUN вернул бы путь туннеля и
ответил бы про другую сеть.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.diag.catalog import is_public_address
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.probes import dns_wire
from src.diag.probes.dns_wire import DnsAnswer
from src.diag.probes.https import family_of
from src.diag.probes.limits import DNS_TRANSPORT_BYTES, DNS_TRANSPORT_TIMEOUT_S
from src.diag.probes.support import (
    ProbeContext,
    TruncatedResponseError,
    classify,
    elapsed_since,
    https_exchange,
    status_of,
)

MAX_DOH_RESPONSE = 16_384
RESOLVER_LITERALS = {
    "google-dns": {AddressFamily.IPV4: "8.8.8.8", AddressFamily.IPV6: "2001:4860:4860::8888"},
    "cloudflare-dns": {AddressFamily.IPV4: "1.1.1.1", AddressFamily.IPV6: "2606:4700:4700::1111"},
}
_POP_CODE = re.compile(r"[A-Za-z]{3}[0-9]{0,3}")


@dataclass(frozen=True)
class DnsProbeResult:
    observation: ProbeObservation
    addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class DohEndpoint:
    id: str
    hostname: str
    bootstrap: tuple[str, ...]
    expires_at: int

    def for_family(self, family: AddressFamily) -> DohEndpoint | None:
        matching = tuple(a for a in self.bootstrap if family_of(a) is family)
        return DohEndpoint(self.id, self.hostname, matching, self.expires_at) if matching else None


# Проверено 2026-10-20. Просроченный bootstrap не подменяется системным DNS.
DOH_ENDPOINTS = (
    DohEndpoint("cloudflare-doh", "cloudflare-dns.com", ("1.1.1.1", "2606:4700:4700::1111"), 1800316800),
    DohEndpoint("google-doh", "dns.google", ("8.8.8.8", "2001:4860:4860::8888"), 1800316800),
)  # fmt: skip


def exchange_udp(context: ProbeContext, server: str, message: bytes, timeout: float) -> bytes:
    sock = context.udp(server, 53, timeout)
    try:
        sock.send(message)
        return sock.recv(DNS_TRANSPORT_BYTES + 1)
    finally:
        context.release(sock)


def exchange_tcp(context: ProbeContext, server: str, message: bytes, timeout: float) -> bytes:
    sock = context.connect(server, 53, timeout)
    try:
        sock.sendall(len(message).to_bytes(2, "big") + message)
        data = bytearray()
        needed = 2
        while len(data) < needed:
            chunk = sock.recv(min(8192, needed - len(data)))
            if not chunk:
                raise TruncatedResponseError("short dns reply")
            data += chunk
            if len(data) == 2:
                needed = 2 + int.from_bytes(data, "big")
                if needed - 2 > dns_wire.MAX_MESSAGE_BYTES:
                    raise TruncatedResponseError("long dns reply")
        return bytes(data[2:])
    finally:
        context.release(sock)


def _ask_server(context, server, hostname, family, timeout) -> DnsAnswer:
    transaction = secrets.randbelow(65536)
    message = dns_wire.with_transaction(dns_wire.query(hostname, family), transaction)
    reply = exchange_udp(context, server, message, timeout)
    if len(reply) >= 3 and reply[2] & 2:
        reply = exchange_tcp(context, server, message, timeout)
    if len(reply) < 2 or int.from_bytes(reply[:2], "big") != transaction:
        raise ValueError("foreign transaction")
    return dns_wire.parse(dns_wire.with_transaction(reply, 0), hostname, family)


def probe_system_dns(
    context: ProbeContext,
    id: str,
    target_id: str,
    hostname: str,
    family: AddressFamily,
    servers: Callable[[], list[str]],
    timeout: float,
) -> DnsProbeResult:
    started = time.monotonic()

    def observation(status, failure=None, answer=None) -> ProbeObservation:
        rcode = "unknown" if answer is None or answer.rcode is None else str(answer.rcode)
        return ProbeObservation(
            id, target_id, ProbeRoute.DIRECT, ProbeStage.DNS, status,
            elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
            evidence={
                "resolver": "system",
                "dnsRcode": rcode,
                "coverage": answer.coverage if answer else "system-path",
            },
        )  # fmt: skip

    known = servers()
    if not known:
        return DnsProbeResult(observation(ProbeStatus.SKIPPED, DiagnosticFailure.DNS_FAILED))
    failure = DiagnosticFailure.IO
    status = ProbeStatus.FAILURE
    for server in known[:2]:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            return DnsProbeResult(observation(ProbeStatus.FAILURE, DiagnosticFailure.TIMEOUT))
        try:
            answer = _ask_server(context, server, hostname, family, remaining)
        except ValueError:
            failure, status = DiagnosticFailure.UNEXPECTED_RESPONSE, ProbeStatus.INCONCLUSIVE
            continue
        except OSError as error:
            failure = classify(error)
            status = status_of(failure)
            continue
        if not all(is_public_address(a) and family_of(a) is family for a in answer.addresses):
            return DnsProbeResult(
                observation(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNSAFE_ADDRESS, answer)
            )
        if answer.rcode != 0 or not answer.addresses:
            return DnsProbeResult(
                observation(ProbeStatus.FAILURE, DiagnosticFailure.DNS_FAILED, answer)
            )
        return DnsProbeResult(observation(ProbeStatus.SUCCESS, None, answer), answer.addresses)
    return DnsProbeResult(observation(status, failure))


def probe_doh(
    context: ProbeContext,
    id: str,
    target_id: str,
    hostname: str,
    family: AddressFamily,
    endpoint: DohEndpoint,
    now: float,
    timeout: float,
) -> DnsProbeResult:
    started = time.monotonic()

    def result(status, failure=None, answer=None, code=None) -> DnsProbeResult:
        rcode = "unknown" if answer is None or answer.rcode is None else str(answer.rcode)
        return DnsProbeResult(
            ProbeObservation(
                id, target_id, ProbeRoute.DIRECT, ProbeStage.DNS, status,
                elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
                http_status=code,
                evidence={
                    "resolver": endpoint.id,
                    "coverage": "independent-bootstrap",
                    "dnsRcode": rcode,
                },
            ),
            answer.addresses if answer and status is ProbeStatus.SUCCESS else (),
        )  # fmt: skip

    if now >= endpoint.expires_at:
        return result(ProbeStatus.UNSUPPORTED, DiagnosticFailure.CONTROL_UNAVAILABLE)

    def read_limit(status, headers) -> int:
        kind = headers.get("content-type", "").split(";")[0].strip().lower()
        length = headers.get("content-length", "")
        if status != 200 or kind != "application/dns-message":
            return 0
        if length.isdigit() and int(length) > MAX_DOH_RESPONSE:
            return 0
        return MAX_DOH_RESPONSE + 1

    try:
        response = https_exchange(
            context,
            hostname=endpoint.hostname,
            path="/dns-query",
            address=endpoint.bootstrap[0],
            method="POST",
            headers={
                "Accept": "application/dns-message",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-store",
                "Content-Type": "application/dns-message",
            },
            body=dns_wire.query(hostname, family),
            timeout=timeout,
            read_limit=read_limit,
        )
    except (OSError, ValueError) as error:
        failure = classify(error)
        return result(status_of(failure), failure)
    code = response.status
    if 300 <= code <= 399:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code=code)
    if code != 200:
        return result(ProbeStatus.FAILURE, DiagnosticFailure.HTTP_REJECTED, code=code)
    if response.content_type.split(";")[0].strip().lower() != "application/dns-message":
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, code=code)
    if not response.complete or len(response.body) > MAX_DOH_RESPONSE:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.BODY_LIMIT, code=code)
    try:
        answer = dns_wire.parse(response.body, hostname, family)
    except ValueError:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE)
    if not all(is_public_address(a) for a in answer.addresses):
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNSAFE_ADDRESS, code=code)
    if answer.rcode == 0 and answer.addresses:
        return result(ProbeStatus.SUCCESS, None, answer, code)
    return result(ProbeStatus.FAILURE, DiagnosticFailure.DNS_FAILED, answer, code)


def _transport_exchange(context, literal, query, *, tcp) -> bytes:
    transaction = secrets.randbelow(65536)
    message = dns_wire.with_transaction(query, transaction)
    exchange = exchange_tcp if tcp else exchange_udp
    response = exchange(context, literal, message, DNS_TRANSPORT_TIMEOUT_S)
    if (
        not 12 <= len(response) <= DNS_TRANSPORT_BYTES
        or int.from_bytes(response[:2], "big") != transaction
    ):
        raise ValueError("foreign response")
    return dns_wire.with_transaction(response, 0)


def probe_dns_transport(
    context: ProbeContext,
    id: str,
    resolver: str,
    family: AddressFamily,
    *,
    tcp: bool,
    route: ProbeRoute = ProbeRoute.DIRECT,
) -> ProbeObservation:
    """Ответ UDP доказывает только этот путь DNS, а не весь UDP."""
    started = time.monotonic()
    transport = "tcp" if tcp else "udp"
    stage = ProbeStage.TCP if tcp else ProbeStage.UDP

    def result(status, failure=None, extra=None) -> ProbeObservation:
        return ProbeObservation(
            id, resolver, route, stage, status,
            elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
            evidence={"transport": transport, "coverage": f"dns-{transport}", **(extra or {})},
        )  # fmt: skip

    if route is not ProbeRoute.DIRECT:
        return result(ProbeStatus.UNSUPPORTED, DiagnosticFailure.TRANSPORT_UNSUPPORTED)
    literal = RESOLVER_LITERALS.get(resolver, {}).get(family)
    if literal is None:
        return result(ProbeStatus.UNSUPPORTED, DiagnosticFailure.CONTROL_UNAVAILABLE)
    query = dns_wire.query("example.com", AddressFamily.IPV4)
    try:
        response = _transport_exchange(context, literal, query, tcp=tcp)
        if response[2] & 2:
            # Вопрос сверяем и в усечённом ответе; TCP — отдельная задача бюджета.
            echoed = bytearray(response[: len(query)])
            echoed[2] &= 0xFD
            echoed[6:12] = bytes(6)
            dns_wire.parse(bytes(echoed), "example.com", AddressFamily.IPV4)
            return result(
                ProbeStatus.INCONCLUSIVE,
                DiagnosticFailure.DNS_TRUNCATED,
                {"coverage": f"dns-{transport}-truncated"},
            )
        answer = dns_wire.parse(response, "example.com", AddressFamily.IPV4)
    except ValueError:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE)
    except OSError as error:
        failure = classify(error)
        return result(status_of(failure), failure)
    evidence = {"dnsRcode": str(answer.rcode), "receivedBytes": str(len(response))}
    if not all(is_public_address(a) for a in answer.addresses):
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNSAFE_ADDRESS, evidence)
    if answer.rcode != 0 or not answer.addresses:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.DNS_FAILED, evidence)
    return result(ProbeStatus.SUCCESS, None, {**evidence, "responseMatched": "true"})


def probe_dns_interception(
    context: ProbeContext, id: str, resolver: str, family: AddressFamily
) -> ProbeObservation:
    """Перехват порта 53. Cloudflare на id.server CH TXT называет площадку, Google на случайное
    имя своей зоны отвечает NXDOMAIN; всё остальное пришло от чужого резолвера."""
    started = time.monotonic()
    identity = resolver == "cloudflare-dns"
    coverage = "dns-identity" if identity else "dns-nxdomain"

    def result(status, failure=None, matched=None) -> ProbeObservation:
        evidence = {"transport": "udp", "coverage": coverage}
        if matched is not None:
            evidence["responseMatched"] = str(matched).lower()
        return ProbeObservation(
            id, resolver, ProbeRoute.DIRECT, ProbeStage.UDP, status,
            elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
            evidence=evidence,
        )  # fmt: skip

    literal = RESOLVER_LITERALS.get(resolver, {}).get(family)
    if literal is None:
        return result(ProbeStatus.UNSUPPORTED, DiagnosticFailure.CONTROL_UNAVAILABLE)
    if identity:
        hostname = "id.server"
        query = dns_wire.query_raw(hostname, dns_wire.TYPE_TXT, dns_wire.CLASS_CHAOS)
    else:
        hostname = f"{secrets.token_hex(8)}.google.com"
        query = dns_wire.query(hostname, AddressFamily.IPV4)
    try:
        response = _transport_exchange(context, literal, query, tcp=False)
        if response[2] & 2:
            return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.DNS_TRUNCATED)
        if identity:
            rcode, texts = dns_wire.parse_txt(response, hostname, dns_wire.CLASS_CHAOS)
            if rcode == 0 and len(texts) == 1 and _POP_CODE.fullmatch(texts[0]):
                return result(ProbeStatus.SUCCESS, matched=True)
            return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, False)
        answer = dns_wire.parse(response, hostname, AddressFamily.IPV4)
    except ValueError:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE)
    except OSError as error:
        failure = classify(error)
        return result(status_of(failure), failure)
    if answer.rcode == 3:
        return result(ProbeStatus.SUCCESS, matched=True)
    if answer.addresses:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNEXPECTED_RESPONSE, False)
    return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.DNS_FAILED)
