"""Loopback-серверы и подмены для тестов диагностики сети. В интернет не ходят."""

from __future__ import annotations

import errno
import socket
import ssl
import struct
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_cert(tmp_path: Path, hostname: str = "localhost") -> tuple[Path, Path]:
    """Самоподписанный сертификат на hostname: ключей в репозитории нет."""
    key, cert = tmp_path / f"{hostname}.key", tmp_path / f"{hostname}.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={hostname}",
            "-addext", f"subjectAltName=DNS:{hostname}",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return key, cert


class ScriptedHttpsServer:
    """HTTPS на loopback: ответ (код, тело, заголовки) задаётся по пути, запросы записываются."""

    def __init__(self, tmp_path: Path, responses, hostname: str = "localhost"):
        key, cert = make_cert(tmp_path, hostname)
        self.cert = cert
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, str], bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                status, payload, headers = outer.responses.get(self.path, (404, b"", {}))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                if "Transfer-Encoding" not in headers:
                    self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except OSError:
                    pass  # проба с лимитом тела закрывает сокет первой

            do_GET = _serve
            do_POST = _serve

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def client_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=str(self.cert))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def parse_query(data: bytes) -> tuple[int, str, int, int]:
    """Разбор запроса независимо от src.diag: тест не должен доверять проверяемому коду."""
    transaction = struct.unpack("!H", data[:2])[0]
    labels, position = [], 12
    while data[position]:
        size = data[position]
        labels.append(data[position + 1 : position + 1 + size].decode("ascii"))
        position += 1 + size
    qtype, qclass = struct.unpack("!HH", data[position + 1 : position + 5])
    return transaction, ".".join(labels), qtype, qclass


def encode_name(name: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


def build_response(
    transaction: int,
    name: str,
    qtype: int,
    qclass: int = 1,
    *,
    rcode: int = 0,
    answers: list[bytes] = (),
    truncated: bool = False,
    answer_type: int | None = None,
) -> bytes:
    flags = 0x8180 | rcode | (0x0200 if truncated else 0)
    head = struct.pack("!HHHHHH", transaction, flags, 1, len(answers), 0, 0)
    question = encode_name(name) + struct.pack("!HH", qtype, qclass)
    records = b"".join(
        b"\xc0\x0c" + struct.pack("!HHIH", answer_type or qtype, qclass, 60, len(r)) + r
        for r in answers
    )
    return head + question + records


def _bind_udp_and_tcp(attempts: int = 50) -> tuple[socket.socket, socket.socket, int]:
    """UDP и TCP на одном номере порта.

    Ядро выбирает номер, свободный только для UDP. Для TCP он может быть занят: например,
    клиентским соединением в TIME_WAIT, которому SO_REUSEADDR не помеха. Поэтому пара
    подбирается заново, а не считается удачной с первого раза.
    """
    while True:
        attempts -= 1
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.bind(("127.0.0.1", 0))
            port = udp.getsockname()[1]
            tcp.bind(("127.0.0.1", port))
            tcp.listen()
        except OSError as error:
            udp.close()
            tcp.close()
            if error.errno != errno.EADDRINUSE or attempts <= 0:
                raise
        else:
            return udp, tcp, port


class FakeDnsServer:
    """UDP и TCP DNS на loopback: `answers[(name, qtype)] = (rcode, [rdata])`.

    `truncate_udp=True` отдаёт по UDP ответ с TC=1: проверка перехода на TCP.
    `silent=True` молчит: проверка таймаута.
    """

    def __init__(self, answers=None, *, truncate_udp=False, silent=False):
        self.answers = answers or {}
        self.truncate_udp = truncate_udp
        self.silent = silent
        self.queries: list[tuple[str, str, int]] = []
        self.udp, self.tcp, self.port = _bind_udp_and_tcp()
        self._stop = threading.Event()
        threading.Thread(target=self._serve_udp, daemon=True).start()
        threading.Thread(target=self._serve_tcp, daemon=True).start()

    def _reply(self, transport: str, data: bytes) -> bytes:
        transaction, name, qtype, qclass = parse_query(data)
        self.queries.append((transport, name, qtype))
        if transport == "udp" and self.truncate_udp:
            return build_response(transaction, name, qtype, qclass, truncated=True)
        rcode, rdata = self.answers.get((name, qtype), (3, []))
        return build_response(transaction, name, qtype, qclass, rcode=rcode, answers=rdata)

    def _serve_udp(self):
        self.udp.settimeout(0.1)
        while not self._stop.is_set():
            try:
                data, peer = self.udp.recvfrom(4096)
            except OSError:
                continue
            if not self.silent:
                self.udp.sendto(self._reply("udp", data), peer)

    def _serve_tcp(self):
        self.tcp.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.tcp.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(1)
                try:
                    length = struct.unpack("!H", conn.recv(2))[0]
                    reply = self._reply("tcp", conn.recv(length))
                    conn.sendall(struct.pack("!H", len(reply)) + reply)
                except OSError:
                    pass

    def close(self):
        self._stop.set()
        self.udp.close()
        self.tcp.close()
