"""Общее для проб: привязанные отменяемые сокеты, разбор ошибок и маленький клиент HTTP/1.1.

requests здесь не подходит: у него нет ни привязки к интерфейсу, ни закрытия сокета извне,
а отмена должна будить поток, ждущий в connect и recv. Тела ответов и тексты исключений за
пределы проб не выходят.
"""

from __future__ import annotations

import base64
import errno
import ipaddress
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from src.diag.models import DiagnosticFailure, ProbeStatus
from src.diag.probes.limits import HEADER_BYTES
from src.diag.scheduler import SocketRegistry


class ProxyAuthError(OSError):
    """HTTP-inbound ответил 407."""


class ProxyUnavailableError(OSError):
    """Локальный inbound сеанса не принимает соединения."""


class TruncatedResponseError(OSError):
    """Соединение закрылось раньше конца ответа."""


class BindRestrictedError(OSError):
    """Под TUN сокет не удалось вывести мимо туннеля: прямой путь не проверить."""


@dataclass(frozen=True)
class TunnelEndpoint:
    port: int
    user: str
    password: str
    host: str = "127.0.0.1"

    def __repr__(self) -> str:
        return f"TunnelEndpoint(port={self.port})"


@dataclass
class ProbeContext:
    """Как пробы открывают сокеты.

    `remap` нужен тестам: публичный адрес уводится на loopback, а проверка адреса остаётся
    настоящей. Поэтому тестам не нужно ослаблять политику, а проба не ходит в сеть.
    """

    bind: Callable[[socket.socket], None] | None = None
    under_tun: bool = False
    sockets: SocketRegistry = field(default_factory=SocketRegistry)
    remap: Callable[[str, int], tuple[str, int]] | None = None
    ssl_context: ssl.SSLContext | None = None

    def tls_context(self) -> ssl.SSLContext:
        if self.ssl_context is None:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.set_alpn_protocols(["http/1.1"])
        return self.ssl_context

    def _destination(self, address: str, port: int) -> tuple[str, int]:
        return self.remap(address, port) if self.remap else (address, port)

    def _bound(self, kind: int, address: str) -> socket.socket:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, kind)
        try:
            if self.bind and not ipaddress.ip_address(address).is_loopback:
                try:
                    self.bind(sock)
                except OSError as error:
                    # Без привязки под TUN проба ушла бы в туннель и исказила прямой путь.
                    if self.under_tun:
                        raise BindRestrictedError(str(error)) from error
            self.sockets.add(sock)
        except BaseException:
            sock.close()
            raise
        return sock

    def connect(self, address: str, port: int, timeout: float) -> socket.socket:
        destination = self._destination(address, port)
        sock = self._bound(socket.SOCK_STREAM, destination[0])
        try:
            sock.settimeout(timeout)
            sock.connect(destination)
        except BaseException:
            self.release(sock)
            raise
        return sock

    def udp(self, address: str, port: int, timeout: float) -> socket.socket:
        destination = self._destination(address, port)
        sock = self._bound(socket.SOCK_DGRAM, destination[0])
        try:
            sock.settimeout(timeout)
            sock.connect(destination)
        except BaseException:
            self.release(sock)
            raise
        return sock

    def wrap_tls(self, sock: socket.socket, hostname: str) -> ssl.SSLSocket:
        # wrap_socket забирает дескриптор: в реестре должен лежать уже TLS-сокет.
        self.sockets.discard(sock)
        secure = self.tls_context().wrap_socket(
            sock, server_hostname=hostname, do_handshake_on_connect=False
        )
        try:
            self.sockets.add(secure)
            secure.do_handshake()
        except BaseException:
            self.release(secure)
            raise
        return secure

    def release(self, sock: socket.socket) -> None:
        self.sockets.discard(sock)
        try:
            sock.close()
        except OSError:
            pass


def classify(error: BaseException, *, under_tun: bool = False) -> DiagnosticFailure:
    """Код отказа по исключению: порт diagnosticFailure() с поправкой на маршруты TUN."""
    if isinstance(error, ProxyAuthError):
        return DiagnosticFailure.PROXY_AUTH
    if isinstance(error, ProxyUnavailableError):
        return DiagnosticFailure.PROXY_UNAVAILABLE
    if isinstance(error, BindRestrictedError | PermissionError):
        return DiagnosticFailure.SYSTEM_RESTRICTED
    if isinstance(error, TruncatedResponseError):
        return DiagnosticFailure.IO
    if isinstance(error, ssl.SSLCertVerificationError):
        return DiagnosticFailure.TLS_CERTIFICATE
    if isinstance(error, TimeoutError | ssl.SSLWantReadError | ssl.SSLWantWriteError):
        return DiagnosticFailure.TIMEOUT
    if isinstance(error, ssl.SSLError):
        return DiagnosticFailure.TLS_FAILED
    if isinstance(error, socket.gaierror):
        return DiagnosticFailure.DNS_FAILED
    code = error.errno if isinstance(error, OSError) else None
    if code in (errno.ENETUNREACH, errno.EHOSTUNREACH) and under_tun:
        # Помощник TUN мог заменить физический маршрут по умолчанию: тогда прямой путь
        # закрыт нашим же туннелем, и это не отказ сети.
        return DiagnosticFailure.SYSTEM_RESTRICTED
    if isinstance(error, ConnectionRefusedError) or code in (
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
    ):
        return DiagnosticFailure.CONNECTION_REFUSED
    if isinstance(error, ConnectionResetError | BrokenPipeError | ConnectionAbortedError):
        return DiagnosticFailure.CONNECTION_RESET
    return DiagnosticFailure.IO


def status_of(failure: DiagnosticFailure) -> ProbeStatus:
    if failure is DiagnosticFailure.SYSTEM_RESTRICTED:
        return ProbeStatus.INCONCLUSIVE
    return ProbeStatus.FAILURE


def elapsed_since(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


@dataclass
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    complete: bool
    tls_version: str | None
    timings: dict[str, str]

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


class _Deadline:
    def __init__(self, timeout: float):
        self.at = time.monotonic() + timeout

    def arm(self, sock: socket.socket) -> None:
        remaining = self.at - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("probe deadline")
        sock.settimeout(remaining)


class _Reader:
    def __init__(self, sock: socket.socket, deadline: _Deadline):
        self.sock = sock
        self.deadline = deadline
        self.buffer = bytearray()
        self.eof = False

    def fill(self, size: int = 8192) -> bool:
        if self.eof:
            return False
        self.deadline.arm(self.sock)
        data = self.sock.recv(size)
        if not data:
            self.eof = True
            return False
        self.buffer += data
        return True

    def head(self) -> tuple[int, dict[str, str]]:
        while True:
            end = self.buffer.find(b"\r\n\r\n")
            if end >= 0:
                break
            if len(self.buffer) > HEADER_BYTES:
                raise TruncatedResponseError("headers too long")
            if not self.fill():
                raise TruncatedResponseError("no response head")
        raw = bytes(self.buffer[:end]).decode("latin-1").split("\r\n")
        del self.buffer[: end + 4]
        parts = raw[0].split(" ", 2)
        if len(parts) < 2 or not parts[0].startswith("HTTP/1.") or not parts[1].isdigit():
            raise TruncatedResponseError("bad status line")
        headers: dict[str, str] = {}
        for line in raw[1:]:
            name, sep, value = line.partition(":")
            if sep:
                headers[name.strip().lower()] = value.strip()
        return int(parts[1]), headers

    def take(self, limit: int) -> bytes:
        taken = bytes(self.buffer[:limit])
        del self.buffer[:limit]
        return taken

    def body(self, headers: Mapping[str, str], limit: int) -> tuple[bytes, bool]:
        if "chunked" in headers.get("transfer-encoding", "").lower():
            return self._chunked(limit)
        length = headers.get("content-length")
        if length is not None and length.isdigit():
            return self._sized(int(length), limit)
        return self._until_close(limit)

    def _sized(self, length: int, limit: int) -> tuple[bytes, bool]:
        wanted = min(length, limit)
        while len(self.buffer) < wanted:
            if not self.fill():
                raise TruncatedResponseError("short body")
        return self.take(wanted), wanted == length

    def _until_close(self, limit: int) -> tuple[bytes, bool]:
        while len(self.buffer) < limit:
            if not self.fill():
                return self.take(limit), True
        return self.take(limit), False

    def _line(self) -> bytes:
        while True:
            end = self.buffer.find(b"\r\n")
            if end >= 0:
                line = bytes(self.buffer[:end])
                del self.buffer[: end + 2]
                return line
            if len(self.buffer) > 1024 or not self.fill():
                raise TruncatedResponseError("bad chunk line")

    def _chunked(self, limit: int) -> tuple[bytes, bool]:
        body = bytearray()
        while len(body) < limit:
            try:
                size = int(self._line().split(b";")[0].strip() or b"x", 16)
            except ValueError as error:
                raise TruncatedResponseError("bad chunk size") from error
            if size == 0:
                return bytes(body), True
            wanted = min(size, limit - len(body))
            while len(self.buffer) < wanted:
                if not self.fill():
                    raise TruncatedResponseError("short chunk")
            body += self.take(wanted)
            if wanted < size:
                return bytes(body), False
            self._line()
        return bytes(body), False


def open_tunnel(
    context: ProbeContext, proxy: TunnelEndpoint, hostname: str, port: int, deadline: _Deadline
) -> socket.socket:
    """CONNECT через health-inbound: тот же сокет потом идёт в обычный TLS."""
    try:
        sock = context.connect(proxy.host, proxy.port, max(0.1, deadline.at - time.monotonic()))
    except (ConnectionRefusedError, ConnectionAbortedError) as error:
        raise ProxyUnavailableError("inbound refused") from error
    try:
        credentials = f"{proxy.user}:{proxy.password}".encode()
        authorization = base64.b64encode(credentials).decode("ascii")
        request = (
            f"CONNECT {hostname}:{port} HTTP/1.1\r\nHost: {hostname}:{port}\r\n"
            f"Proxy-Authorization: Basic {authorization}\r\n\r\n"
        )
        deadline.arm(sock)
        sock.sendall(request.encode("ascii"))
        reader = _Reader(sock, deadline)
        status, _ = reader.head()
        if status == 407:
            raise ProxyAuthError("proxy rejected credentials")
        if status != 200 or reader.buffer:
            raise OSError("unexpected proxy response")
    except BaseException:
        context.release(sock)
        raise
    return sock


def https_exchange(
    context: ProbeContext,
    *,
    hostname: str,
    path: str,
    address: str | None,
    proxy: TunnelEndpoint | None = None,
    port: int = 443,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes = b"",
    timeout: float,
    read_limit: Callable[[int, Mapping[str, str]], int],
) -> HttpResponse:
    """Один запрос HTTPS на закреплённый адрес. Редиректы не выполняются, соединение не живёт.

    `read_limit(status, headers)` решает, сколько тела читать, уже зная заголовки: например,
    не качать ничего при слишком большом Content-Length.
    """
    if (address is None) == (proxy is None):
        raise ValueError("exactly one of address and proxy is required")
    deadline = _Deadline(timeout)
    timings: dict[str, str] = {}
    started = time.monotonic()
    if proxy is not None:
        raw = open_tunnel(context, proxy, hostname, port, deadline)
    else:
        raw = context.connect(address or "", port, timeout)
        timings["tcpMs"] = str(elapsed_since(started))
    tls_started = time.monotonic()
    sock: socket.socket = raw
    try:
        deadline.arm(sock)
        sock = context.wrap_tls(raw, hostname)
        timings["tlsMs"] = str(elapsed_since(tls_started))
        lines = [f"{method} {path} HTTP/1.1", f"Host: {hostname}", "Connection: close"]
        for name, value in (headers or {}).items():
            lines.append(f"{name}: {value}")
        if method != "GET":
            lines.append(f"Content-Length: {len(body)}")
        deadline.arm(sock)
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body)
        sent = time.monotonic()
        reader = _Reader(sock, deadline)
        status, response_headers = reader.head()
        timings["headersMs"] = str(elapsed_since(sent))
        body_started = time.monotonic()
        limit = read_limit(status, response_headers)
        if status in (204, 304):
            content, complete = b"", True  # такие ответы тела не имеют, ждать закрытия незачем
        elif limit > 0:
            content, complete = reader.body(response_headers, limit)
        else:
            content, complete = b"", False
        timings["bodyMs"] = str(elapsed_since(body_started))
        version = sock.version() if isinstance(sock, ssl.SSLSocket) else None
        return HttpResponse(status, response_headers, content, complete, version, timings)
    except OSError as error:
        error.timings = timings  # type: ignore[attr-defined]
        raise
    finally:
        context.release(sock)
