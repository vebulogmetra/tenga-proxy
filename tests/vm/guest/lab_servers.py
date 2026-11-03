"""«Интернет» лаборатории: запускается в сетевом пространстве `inet` внутри виртуалки.

Эхо-сервер отвечает адресом клиента, DNS-сервер пишет каждый запрос. По этим журналам
проверки видят утечку: запрос с адреса самой машины, а не с выхода прокси.
"""

from __future__ import annotations

import json
import socket
import socketserver
import ssl
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_DIR = Path(sys.argv[1])
_lock = threading.Lock()

DNS_RECORDS = {"b.veblock.test": "203.0.113.11"}
DEFAULT_ADDRESS = "203.0.113.80"


DNS_ADDRESSES = ("192.168.200.1", "203.0.113.53", "1.1.1.1")  # роутер, публичный, основной


def write_log(log_file: str, **entry) -> None:
    with _lock, (LOG_DIR / log_file).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\n")


def client_address(raw: str) -> str:
    return raw.removeprefix("::ffff:")


class Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        source = client_address(self.client_address[0])
        write_log("echo.jsonl", src=source, path=self.path)
        body = source.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


class DualStackServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def parse_question(data: bytes) -> tuple[str, int, int]:
    labels = []
    offset = 12
    while data[offset]:
        length = data[offset]
        labels.append(data[offset + 1 : offset + 1 + length].decode("ascii", "replace"))
        offset += length + 1
    offset += 1
    query_type = struct.unpack("!H", data[offset : offset + 2])[0]
    return ".".join(labels), query_type, offset + 4


def answer(data: bytes) -> bytes:
    name, query_type, end = parse_question(data)
    flags = 0x8180
    question = data[12:end]
    if query_type == 1:
        address = socket.inet_aton(DNS_RECORDS.get(name.lower(), DEFAULT_ADDRESS))
        record = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, 4) + address
        count = 1
    else:
        # IPv6 в лаборатории адресуется напрямую, по именам — только IPv4.
        record = b""
        count = 0
    return data[:2] + struct.pack("!HHHHH", flags, 1, count, 0, 0) + question + record


class Dns(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data, sock = self.request
        try:
            name, query_type, _end = parse_question(data)
            write_log("dns.jsonl", src=self.client_address[0], name=name.lower(), type=query_type)
            sock.sendto(answer(data), self.client_address)
        except (IndexError, struct.error, OSError):
            pass


class ThreadingUdp(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_tls(cert: str, key: str) -> None:
    """Сайт-маска для Reality: сервер пересылает ему чужие рукопожатия."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    context.set_alpn_protocols(["h2", "http/1.1"])
    listener = socket.create_server(("127.0.0.1", 8443))

    def handle(connection: socket.socket) -> None:
        try:
            with context.wrap_socket(connection, server_side=True) as stream:
                stream.recv(4096)
                stream.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        except OSError:
            pass

    while True:
        connection, _address = listener.accept()
        threading.Thread(target=handle, args=(connection,), daemon=True).start()


def main() -> None:
    threading.Thread(target=serve_tls, args=(sys.argv[2], sys.argv[3]), daemon=True).start()
    # По сокету на адрес: ответ с общего 0.0.0.0 ушёл бы с адреса шлюза, и клиент его отбросил бы
    for address in DNS_ADDRESSES:
        server = ThreadingUdp((address, 53), Dns)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    DualStackServer(("::", 80), Echo).serve_forever()


if __name__ == "__main__":
    main()
