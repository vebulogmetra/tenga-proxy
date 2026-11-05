"""Пробы на loopback: публичный адрес уводит `remap`, политика адресов остаётся настоящей."""

import errno
import socket
import struct
import threading

import pytest

from src.core.http_probe import ProbeCredentials, ProbeEndpoint
from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget
from src.diag.models import AddressFamily, DiagnosticFailure, ProbeRoute, ProbeStage, ProbeStatus
from src.diag.probes import dns as dns_probes
from src.diag.probes import dns_wire
from src.diag.probes.connection import probe_tcp, probe_tls
from src.diag.probes.https import probe_https
from src.diag.probes.media import is_image, is_video, probe_media, telegram_image, youtube_video
from src.diag.probes.support import (
    BindRestrictedError,
    ProbeContext,
    ProxyAuthError,
    ProxyUnavailableError,
    TunnelEndpoint,
    classify,
)
from src.diag.probes.telegram import handshake_matches, handshake_request, probe_telegram
from src.diag.scheduler import SocketRegistry
from src.diag.session import TunnelSessionSource
from tests.support.diag import FakeDnsServer, ScriptedHttpsServer, build_response, parse_query

PUBLIC = "1.1.1.1"
HOST = "origin.example"
V4 = (AddressFamily.IPV4,)


def target(**changes):
    values = {
        "id": "test", "hostname": HOST, "placement_group": "g", "max_bytes": 64, "families": V4,
    }  # fmt: skip
    values.update(changes)
    return DiagnosticTarget(**values)


@pytest.fixture
def https(tmp_path):
    servers = []

    def start(responses, hostname=HOST):
        server = ScriptedHttpsServer(tmp_path, responses, hostname)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def context_for(server, **changes):
    return ProbeContext(
        remap=lambda _a, _p: ("127.0.0.1", server.port),
        ssl_context=server.client_context(),
        **changes,
    )


def run_https(server, tgt=None, address=PUBLIC, timeout=3):
    tgt = tgt or target()
    return probe_https(context_for(server), "p", tgt, ProbeRoute.DIRECT, timeout, address)


def test_success_records_evidence_without_body(https):
    server = https({"/": (200, b"ok", {})})
    result = run_https(server, target(expected_body="ok", expected_status=200))
    assert result.status is ProbeStatus.SUCCESS
    assert result.evidence["responseMatched"] == "true"
    assert result.evidence["receivedBytes"] == "2"
    assert result.evidence["tlsVersion"].startswith("TLS")
    assert "ok" not in result.evidence.values()


def test_body_mismatch_is_unexpected_response(https):
    result = run_https(https({"/": (200, b"no", {})}), target(expected_body="ok"))
    assert result.status is ProbeStatus.FAILURE
    assert result.failure_code is DiagnosticFailure.UNEXPECTED_RESPONSE


def test_redirect_is_recorded_not_followed(https):
    server = https({"/": (302, b"", {"Location": "https://evil.example/"})})
    result = run_https(server)
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.http_status == 302
    assert len(server.requests) == 1


def test_rejection_and_proxy_auth_differ(https):
    assert run_https(https({"/": (403, b"", {})})).failure_code is DiagnosticFailure.HTTP_REJECTED
    assert run_https(https({"/": (407, b"", {})})).failure_code is DiagnosticFailure.PROXY_AUTH


def test_oversized_body_is_not_downloaded(https):
    result = run_https(https({"/": (200, b"x" * 1000, {})}))
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.failure_code is DiagnosticFailure.BODY_LIMIT
    assert result.evidence["receivedBytes"] == "0"


def test_web_entry_reads_prefix_and_passes(https):
    tgt = target(purpose=DiagnosticPurpose.TELEGRAM_WEB, max_bytes=65536)
    result = run_https(https({"/": (200, b"x" * 8000, {})}), tgt)
    assert result.status is ProbeStatus.SUCCESS
    assert result.evidence["coverage"] == "web-entry-only"
    assert result.evidence["receivedBytes"] == "4096"


def test_challenge_page_is_not_success(https):
    result = run_https(https({"/": (200, b"<html>cf-chl-bypass</html>", {})}))
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.evidence["coverage"] == "web-challenge"


def test_robots_response_must_look_like_robots(https):
    tgt = target(coverage="robots-response")
    good = run_https(https({"/": (200, b"User-Agent: *\nDisallow:\n", {})}), tgt)
    assert good.status is ProbeStatus.SUCCESS
    bad = run_https(https({"/": (200, b"<html>blocked</html>", {})}), tgt)
    assert bad.failure_code is DiagnosticFailure.UNEXPECTED_RESPONSE


def test_instagram_static_needs_webp(https):
    tgt = target(purpose=DiagnosticPurpose.INSTAGRAM_MEDIA)
    webp = b"RIFF\0\0\0\0WEBPdata"
    ok = run_https(https({"/": (200, webp, {"Content-Type": "image/webp"})}), tgt)
    assert ok.status is ProbeStatus.SUCCESS
    wrong = run_https(https({"/": (200, webp, {"Content-Type": "text/html"})}), tgt)
    assert wrong.status is ProbeStatus.INCONCLUSIVE


def test_chunked_body_is_decoded(https):
    chunked = b"2\r\nok\r\n0\r\n\r\n"
    result = run_https(
        https({"/": (200, chunked, {"Transfer-Encoding": "chunked"})}), target(expected_body="ok")
    )
    assert result.status is ProbeStatus.SUCCESS


def test_unsafe_and_unsupported_addresses_do_not_connect(https):
    server = https({"/": (200, b"", {})})
    unsafe = run_https(server, address="10.0.0.1")
    assert unsafe.failure_code is DiagnosticFailure.UNSAFE_ADDRESS
    assert run_https(server, address="2606:4700::1").status is ProbeStatus.UNSUPPORTED
    assert server.requests == []


def test_certificate_for_other_name_is_rejected(https):
    server = https({"/": (200, b"", {})}, hostname="other.example")
    assert run_https(server).failure_code is DiagnosticFailure.TLS_CERTIFICATE


def test_tcp_probe_and_refused_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    context = ProbeContext(remap=lambda _a, _p: ("127.0.0.1", port))
    assert probe_tcp(context, "t", target(), PUBLIC, 1).status is ProbeStatus.SUCCESS
    assert (
        probe_tcp(context, "t", target(), "10.0.0.1", 1).failure_code
        is DiagnosticFailure.UNSAFE_ADDRESS
    )
    server.close()
    # Windows повторяет SYN к закрытому порту около 2 с: короткий таймаут дал бы TIMEOUT.
    refused = probe_tcp(context, "t", target(), PUBLIC, 5)
    assert refused.status is ProbeStatus.FAILURE
    assert refused.failure_code is DiagnosticFailure.CONNECTION_REFUSED


def test_tls_probe_reports_version_and_timeout(https):
    result = probe_tls(context_for(https({})), "t", target(), PUBLIC, 3)
    assert result.status is ProbeStatus.SUCCESS
    assert result.evidence["tlsVersion"].startswith("TLS")
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    port = silent.getsockname()[1]
    context = ProbeContext(remap=lambda _a, _p: ("127.0.0.1", port))
    assert probe_tls(context, "t", target(), PUBLIC, 0.1).failure_code is DiagnosticFailure.TIMEOUT
    silent.close()


def test_closing_registry_wakes_stuck_handshake():
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    port = silent.getsockname()[1]
    registry = SocketRegistry()
    context = ProbeContext(remap=lambda _a, _p: ("127.0.0.1", port), sockets=registry)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(probe_tls(context, "t", target(), PUBLIC, 30))
    )
    worker.start()
    silent.accept()
    threading.Event().wait(0.1)
    registry.close_all()
    worker.join(3)
    silent.close()
    assert not worker.is_alive()
    assert results[0].status is not ProbeStatus.SUCCESS


class FakeProxy:
    """CONNECT на loopback: проверяет Basic и сращивает сокет с целью."""

    def __init__(self, upstream_port, status=200):
        self.upstream_port = upstream_port
        self.status = status
        self.requests = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(4096)
        self.requests.append(data.decode())
        conn.sendall(f"HTTP/1.1 {self.status} X\r\n\r\n".encode())
        if self.status != 200:
            conn.close()
            return
        upstream = socket.create_connection(("127.0.0.1", self.upstream_port))
        for src, dst in ((conn, upstream), (upstream, conn)):
            threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    @staticmethod
    def _pipe(src, dst):
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def close(self):
        self.sock.close()


def test_tunnel_probe_sends_host_and_basic_auth(https):
    server = https({"/": (200, b"ok", {})})
    proxy = FakeProxy(server.port)
    context = ProbeContext(ssl_context=server.client_context())
    result = probe_https(
        context, "p", target(expected_body="ok"), ProbeRoute.ACTIVE_TUNNEL, 3,
        proxy=TunnelEndpoint(proxy.port, "user", "secret"),
    )  # fmt: skip
    proxy.close()
    assert result.status is ProbeStatus.SUCCESS
    assert result.address_family is None
    assert f"CONNECT {HOST}:443" in proxy.requests[0]
    assert "Proxy-Authorization: Basic dXNlcjpzZWNyZXQ=" in proxy.requests[0]


def test_tunnel_auth_rejection_and_dead_inbound():
    proxy = FakeProxy(0, status=407)
    tunnel = TunnelEndpoint(proxy.port, "u", "p")
    context = ProbeContext()
    rejected = probe_https(context, "p", target(), ProbeRoute.ACTIVE_TUNNEL, 2, proxy=tunnel)
    assert rejected.failure_code is DiagnosticFailure.PROXY_AUTH
    proxy.close()
    # close() не снимает порт, пока поток ждёт в accept: берём заведомо свободный.
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    closed_port = free.getsockname()[1]
    free.close()
    tunnel = TunnelEndpoint(closed_port, "u", "p")
    # Таймаут с запасом: Windows повторяет SYN к закрытому порту около 2 с.
    dead = probe_https(context, "p", target(), ProbeRoute.ACTIVE_TUNNEL, 5, proxy=tunnel)
    assert dead.failure_code is DiagnosticFailure.PROXY_UNAVAILABLE


def test_tunnel_endpoint_repr_hides_credentials():
    assert "secret" not in repr(TunnelEndpoint(1, "user", "secret"))


def test_session_token_changes_with_endpoint():
    endpoint = [ProbeEndpoint(10, ProbeCredentials("u", "p"))]
    source = TunnelSessionSource(lambda: endpoint[0])
    first = source.current()
    assert source.is_current(first)
    assert "p" not in repr(first).replace("TunnelSession", "")
    endpoint[0] = ProbeEndpoint(11, ProbeCredentials("u", "p"))
    assert not source.is_current(first)
    endpoint[0] = None
    assert source.current() is None
    endpoint[0] = ProbeEndpoint(12, ProbeCredentials("u", "p"), host="192.168.0.1")
    assert source.current() is None


def test_bind_failure_is_ignored_without_tun():
    def deny(_sock):
        raise OSError("no device")

    sock = ProbeContext(bind=deny)._bound(socket.SOCK_STREAM, PUBLIC)
    sock.close()


def test_loopback_destination_is_never_bound():
    def deny(_sock):
        raise AssertionError("loopback must not be bound")

    sock = ProbeContext(bind=deny, under_tun=True)._bound(socket.SOCK_STREAM, "127.0.0.1")
    sock.close()


def test_bound_socket_is_restricted_under_tun():
    def deny(_sock):
        raise OSError("no device")

    context = ProbeContext(bind=deny, under_tun=True)
    with pytest.raises(BindRestrictedError):
        context.connect(PUBLIC, 443, 1)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError(), DiagnosticFailure.TIMEOUT),
        (ConnectionRefusedError(), DiagnosticFailure.CONNECTION_REFUSED),
        (ConnectionResetError(), DiagnosticFailure.CONNECTION_RESET),
        (BrokenPipeError(), DiagnosticFailure.CONNECTION_RESET),
        (PermissionError(), DiagnosticFailure.SYSTEM_RESTRICTED),
        (socket.gaierror(), DiagnosticFailure.DNS_FAILED),
        (ProxyAuthError(), DiagnosticFailure.PROXY_AUTH),
        (ProxyUnavailableError(), DiagnosticFailure.PROXY_UNAVAILABLE),
        (OSError(), DiagnosticFailure.IO),
        (OSError(errno.ENETUNREACH, "unreachable"), DiagnosticFailure.CONNECTION_REFUSED),
        (OSError(errno.EHOSTUNREACH, "unreachable"), DiagnosticFailure.CONNECTION_REFUSED),
    ],
)
def test_classify(error, code):
    assert classify(error) is code


def dns_context(server):
    return ProbeContext(remap=lambda _a, _p: ("127.0.0.1", server.port))


def system(server, hostname=HOST, family=AddressFamily.IPV4, servers=("192.0.2.1",), timeout=1):
    return dns_probes.probe_system_dns(
        dns_context(server), "d", "t", hostname, family, lambda: list(servers), timeout
    )


A = dns_wire.TYPE_A


def test_system_dns_returns_public_addresses_only_in_the_result():
    server = FakeDnsServer({(HOST, A): (0, [socket.inet_aton("8.8.4.4")])})
    result = system(server)
    assert result.addresses == ("8.8.4.4",)
    assert result.observation.status is ProbeStatus.SUCCESS
    assert result.observation.evidence["resolver"] == "system"
    assert "8.8.4.4" not in str(result.observation.evidence)


def test_system_dns_rejects_private_answer():
    server = FakeDnsServer({(HOST, A): (0, [socket.inet_aton("10.0.0.1")])})
    result = system(server)
    assert result.addresses == ()
    assert result.observation.failure_code is DiagnosticFailure.UNSAFE_ADDRESS


def test_system_dns_nxdomain_timeout_and_no_servers():
    assert system(FakeDnsServer()).observation.failure_code is DiagnosticFailure.DNS_FAILED
    silent = FakeDnsServer(silent=True)
    assert system(silent, timeout=0.2).observation.failure_code is DiagnosticFailure.TIMEOUT
    skipped = system(FakeDnsServer(), servers=())
    assert skipped.observation.status is ProbeStatus.SKIPPED
    assert skipped.observation.failure_code is DiagnosticFailure.DNS_FAILED


def test_truncated_udp_retries_over_tcp():
    server = FakeDnsServer({(HOST, A): (0, [socket.inet_aton("8.8.4.4")])}, truncate_udp=True)
    assert system(server).addresses == ("8.8.4.4",)
    assert [q[0] for q in server.queries] == ["udp", "tcp"]


def doh_endpoint(expires=2_000_000_000):
    return dns_probes.DohEndpoint("cloudflare-doh", HOST, (PUBLIC,), expires)


def doh(server, now=1_000_000_000, **kw):
    return dns_probes.probe_doh(
        context_for(server), "d", "t", "name.example", AddressFamily.IPV4,
        kw.get("endpoint") or doh_endpoint(), now, 3,
    )  # fmt: skip


def doh_reply(rcode=0, answers=(socket.inet_aton("8.8.4.4"),)):
    return build_response(0, "name.example", A, rcode=rcode, answers=list(answers))


CT = {"Content-Type": "application/dns-message"}


def test_doh_posts_a_zero_id_query_and_parses_answer(https):
    server = https({"/dns-query": (200, doh_reply(), CT)})
    result = doh(server)
    assert result.addresses == ("8.8.4.4",)
    assert result.observation.evidence["coverage"] == "independent-bootstrap"
    method, path, headers, body = server.requests[0]
    assert (method, path) == ("POST", "/dns-query")
    assert headers["Accept"] == "application/dns-message"
    assert parse_query(body)[:2] == (0, "name.example")


def test_doh_expired_bootstrap_is_unsupported(https):
    server = https({})
    result = doh(server, now=3_000_000_000)
    assert result.observation.status is ProbeStatus.UNSUPPORTED
    assert server.requests == []


def test_doh_rejects_wrong_type_garbage_and_unsafe(https):
    wrong = doh(https({"/dns-query": (200, doh_reply(), {"Content-Type": "text/html"})}))
    assert wrong.observation.failure_code is DiagnosticFailure.UNEXPECTED_RESPONSE
    garbage = doh(https({"/dns-query": (200, b"\0\0\0", CT)}))
    assert garbage.observation.status is ProbeStatus.INCONCLUSIVE
    private = doh_reply(answers=(socket.inet_aton("10.0.0.1"),))
    assert (
        doh(https({"/dns-query": (200, private, CT)})).observation.failure_code
        is DiagnosticFailure.UNSAFE_ADDRESS
    )
    assert doh(https({"/dns-query": (200, doh_reply(3, ()), CT)})).addresses == ()


@pytest.mark.parametrize("tcp", [False, True])
def test_dns_transport_success(tcp):
    server = FakeDnsServer({("example.com", A): (0, [socket.inet_aton("93.184.216.34")])})
    result = dns_probes.probe_dns_transport(
        dns_context(server), "x", "google-dns", AddressFamily.IPV4, tcp=tcp
    )
    assert result.status is ProbeStatus.SUCCESS
    assert result.stage is (ProbeStage.TCP if tcp else ProbeStage.UDP)
    assert result.evidence["coverage"] == ("dns-tcp" if tcp else "dns-udp")


def test_dns_transport_truncated_and_unknown_resolver():
    server = FakeDnsServer(truncate_udp=True)
    result = dns_probes.probe_dns_transport(
        dns_context(server), "x", "google-dns", AddressFamily.IPV4, tcp=False
    )
    assert result.failure_code is DiagnosticFailure.DNS_TRUNCATED
    unknown = dns_probes.probe_dns_transport(
        dns_context(server), "x", "other", AddressFamily.IPV4, tcp=False
    )
    assert unknown.failure_code is DiagnosticFailure.CONTROL_UNAVAILABLE


def test_interception_nxdomain_means_real_google():
    result = dns_probes.probe_dns_interception(
        dns_context(FakeDnsServer()), "x", "google-dns", AddressFamily.IPV4
    )
    assert result.status is ProbeStatus.SUCCESS
    assert result.evidence["responseMatched"] == "true"


class AnyNameDns(FakeDnsServer):
    def __init__(self, reply_for):
        self.reply_for = reply_for
        super().__init__()

    def _reply(self, transport, data):
        return self.reply_for(*parse_query(data))


def test_interception_detects_hijacking_resolver():
    hijack = AnyNameDns(
        lambda txid, name, qtype, qclass: build_response(
            txid, name, qtype, qclass, answers=[socket.inet_aton("195.1.1.1")]
        )
    )
    result = dns_probes.probe_dns_interception(
        dns_context(hijack), "x", "google-dns", AddressFamily.IPV4
    )
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.evidence["responseMatched"] == "false"


def test_cloudflare_identity_expects_pop_code():
    def identity(text):
        return AnyNameDns(
            lambda txid, name, qtype, qclass: build_response(
                txid, name, qtype, qclass, answers=[bytes([len(text)]) + text]
            )
        )

    good = dns_probes.probe_dns_interception(
        dns_context(identity(b"dme01")), "x", "cloudflare-dns", AddressFamily.IPV4
    )
    assert good.status is ProbeStatus.SUCCESS
    bad = dns_probes.probe_dns_interception(
        dns_context(identity(b"my-router-name")), "x", "cloudflare-dns", AddressFamily.IPV4
    )
    assert bad.evidence["responseMatched"] == "false"


def res_pq(nonce, pq=b"\x17\xed\x48\x94\x1a\x08\xf9\x81"):
    payload = struct.pack("<I", 0x05162463) + nonce + bytes(16)
    payload += bytes([len(pq)]) + pq
    payload += bytes((4 - (len(pq) + 1) % 4) % 4)
    payload += struct.pack("<Ii", 0x1CB5C415, 1) + bytes(8)
    return struct.pack("<qQi", 0, 1, len(payload)) + payload


NONCE = bytes(range(16))


def test_handshake_request_and_reply_shape():
    packet = handshake_request(NONCE, 1_700_000_000_123)
    assert len(packet) == 40
    assert struct.unpack_from("<I", packet, 20)[0] == 0xBE7E8EF1
    message_id = struct.unpack_from("<Q", packet, 8)[0]
    assert message_id % 4 == 0
    assert handshake_matches(res_pq(NONCE), NONCE)
    assert not handshake_matches(res_pq(bytes(16)), NONCE)
    assert not handshake_matches(res_pq(NONCE) + b"x", NONCE)
    assert not handshake_matches(b"\0" * 100, NONCE)


def test_telegram_probe_uses_post_and_never_reads_too_much(https):
    tgt = target(purpose=DiagnosticPurpose.TELEGRAM_APP, path="/api")
    server = https({"/api": (200, b"nope", {})})
    result = probe_telegram(context_for(server), "t", tgt, ProbeRoute.DIRECT, 3, PUBLIC)
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.failure_code is DiagnosticFailure.UNEXPECTED_RESPONSE
    assert result.evidence["coverage"] == "mtproto-first-exchange"
    assert server.requests[0][0] == "POST"
    assert len(server.requests[0][3]) == 40
    big = https({"/api": (200, b"x" * 5000, {})})
    limited = probe_telegram(context_for(big), "t", tgt, ProbeRoute.DIRECT, 3, PUBLIC)
    assert limited.failure_code is DiagnosticFailure.BODY_LIMIT
    rejected = https({"/api": (404, b"", {})})
    refused = probe_telegram(context_for(rejected), "t", tgt, ProbeRoute.DIRECT, 3, PUBLIC)
    assert refused.failure_code is DiagnosticFailure.HTTP_REJECTED


TG_HTML = (
    '<html><meta name="x"><meta property="og:image" '
    'content="https://cdn4.telesco.pe/file/a.jpg?x=1&amp;y=2"></html>'
)
JPEG = b"\xff\xd8\xff" + b"\0" * 600


def test_media_parsers_are_narrow():
    assert telegram_image(TG_HTML) == "https://cdn4.telesco.pe/file/a.jpg?x=1&y=2"
    assert telegram_image(TG_HTML.replace("telesco.pe", "evil.example")) is None
    assert telegram_image("<html></html>") is None
    player = (
        'var ytInitialPlayerResponse = {"playabilityStatus":{"status":"OK"},'
        '"streamingData":{"formats":[{"mimeType":"video/mp4",'
        '"url":"https://r1.googlevideo.com/v?id=1"}]}};'
    )
    assert youtube_video(player) == "https://r1.googlevideo.com/v?id=1"
    assert youtube_video(player.replace('"OK"', '"ERROR"')) is None
    assert youtube_video(player.replace("googlevideo.com", "evil.example")) is None
    assert youtube_video("ytInitialPlayerResponse = {broken") is None
    assert is_image(JPEG, "image/jpeg")
    assert not is_image(JPEG, "text/html")
    assert is_video(b"\0\0\0\x20ftyp" + b"\0" * 1100, "video/mp4")
    assert not is_video(b"\0" * 1100, "video/mp4")


def media_target():
    return target(
        id="tg-media", hostname="t.me", purpose=DiagnosticPurpose.TELEGRAM_MEDIA,
        path="/telegram/319",
    )  # fmt: skip


def test_media_probe_walks_page_and_fragment(tmp_path):
    # Страница и CDN — разные имена: один сервер с сертификатом на оба не нужен, CDN резолвится.
    page = ScriptedHttpsServer(tmp_path, {"/telegram/319": (200, TG_HTML.encode(), {})}, "t.me")
    cdn = ScriptedHttpsServer(
        tmp_path,
        {"/file/a.jpg?x=1&y=2": (206, JPEG, {"Content-Type": "image/jpeg"})},
        "cdn4.telesco.pe",
    )
    context = ProbeContext(
        remap=lambda a, _p: ("127.0.0.1", cdn.port if a == "8.8.4.4" else page.port),
    )
    context.ssl_context = page.client_context()
    context.ssl_context.load_verify_locations(cafile=str(cdn.cert))
    result = probe_media(
        context, "m", media_target(), ProbeRoute.DIRECT, PUBLIC, lambda _h, _f: ("8.8.4.4",)
    )
    page.close()
    cdn.close()
    assert result.status is ProbeStatus.SUCCESS
    assert result.http_status == 206
    assert result.evidence["mediaStage"] == "media"
    assert cdn.requests[0][2]["Range"] == "bytes=0-16383"
    assert "telesco" not in str(result.evidence)


def test_media_probe_conclusions_on_changed_site(https):
    server = https({"/telegram/319": (200, b"<html></html>", {})}, hostname="t.me")
    result = probe_media(
        context_for(server), "m", media_target(), ProbeRoute.DIRECT, PUBLIC, lambda _h, _f: ()
    )
    assert result.status is ProbeStatus.INCONCLUSIVE
    assert result.evidence["mediaDetail"] == "media-url-unavailable"
    missing = https({}, hostname="t.me")
    rejected = probe_media(
        context_for(missing), "m", media_target(), ProbeRoute.DIRECT, PUBLIC, lambda _h, _f: ()
    )
    assert rejected.failure_code is DiagnosticFailure.HTTP_REJECTED


def _busy_tcp_ports(monkeypatch, busy):
    """Первые `busy` привязок TCP отвечают «порт занят», как порт клиента в TIME_WAIT."""

    class Busy(socket.socket):
        left = busy
        created = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            Busy.created.append(self)

        def bind(self, address):
            if self.type == socket.SOCK_STREAM and Busy.left > 0:
                Busy.left -= 1
                raise OSError(errno.EADDRINUSE, "Address already in use")
            super().bind(address)

    monkeypatch.setattr(socket, "socket", Busy)
    return Busy


def test_fake_dns_takes_another_port_when_tcp_one_is_busy(monkeypatch):
    # UDP и TCP считают занятость порозь: свободный для UDP номер может быть занят для TCP.
    busy = _busy_tcp_ports(monkeypatch, busy=3)
    server = FakeDnsServer()
    try:
        assert server.udp.getsockname()[1] == server.tcp.getsockname()[1] == server.port
        abandoned = [s for s in busy.created if s not in (server.udp, server.tcp)]
        assert len(abandoned) == 6
        assert all(s.fileno() == -1 for s in abandoned)
    finally:
        server.close()


def test_fake_dns_gives_up_with_the_original_error_and_no_leaks(monkeypatch):
    busy = _busy_tcp_ports(monkeypatch, busy=10_000)
    with pytest.raises(OSError, match="already in use") as caught:
        FakeDnsServer()
    assert caught.value.errno == errno.EADDRINUSE
    assert busy.left > 0, "число попыток ограничено"
    assert all(s.fileno() == -1 for s in busy.created)
