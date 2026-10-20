import pytest

from src.sub.url_policy import SubscriptionPolicyError, resolve_destination, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/sub",
        "https://u:p@example.com/sub",
        "https://example.com/#secret",
        "https://localhost/sub",
        "https://127.1/sub",
        "https://2130706433/sub",
        "https://0177.0.0.1/sub",
        "https://0x7f000001/sub",
        "https://[::1]/sub",
        "https://[::ffff:127.0.0.1]/sub",
        "https://169.254.169.254/sub",
        "https://example.com:65536/sub",
        "https://example.com:0/sub",
        "https://a.local/sub",
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(SubscriptionPolicyError):
        validate_url(url)


def test_accepts_public_https():
    assert validate_url("https://example.com/a?token=secret").hostname == "example.com"


def test_dns_rebinding_answer_is_rejected():
    def resolver(*args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    with pytest.raises(SubscriptionPolicyError):
        resolve_destination("https://example.com/sub", resolver=resolver)


def test_explicit_source_exception_does_not_transfer():
    validate_url("http://localhost/sub", exceptions=["http://localhost/sub"])
    with pytest.raises(SubscriptionPolicyError):
        validate_url("http://localhost/other", exceptions=["http://localhost/sub"])


def test_pinned_transport_uses_numeric_connect_and_original_tls_name(monkeypatch):
    from unittest.mock import Mock

    from src.sub.url_policy import pinned_get

    session = Mock()
    monkeypatch.setattr("src.sub.url_policy.requests.Session", lambda: session)
    monkeypatch.setattr(
        "src.sub.url_policy.socket.getaddrinfo",
        lambda *_a, **_kw: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    pinned_get(
        "https://example.com/sub",
        headers={},
        timeout=30,
        verify=True,
        proxies={"https": "http://127.0.0.1:8080"},
    )
    assert session.get.call_args.args[0] == "https://93.184.216.34/sub"
    assert session.get.call_args.kwargs["headers"]["Host"] == "example.com"
    assert session.trust_env is False
    adapter = session.mount.call_args.args[1]
    request = __import__("requests").Request("GET", "https://93.184.216.34/sub").prepare()
    _, kwargs = adapter.build_connection_pool_key_attributes(request, True)
    assert kwargs["server_hostname"] == "example.com"
    assert kwargs["assert_hostname"] == "example.com"


def test_redirect_to_lan_is_final_and_never_falls_back(monkeypatch):
    import requests

    from src.sub.updater import SubscriptionUpdater

    calls = []

    def get(url, **kwargs):
        calls.append(url)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "https://127.0.0.1/secret"
        response._content = b""
        response._content_consumed = True
        return response

    monkeypatch.setattr("src.sub.updater.pinned_get", get)
    with pytest.raises(SubscriptionPolicyError):
        SubscriptionUpdater(proxy_url=lambda: "http://127.0.0.1:8080").fetch(
            "https://example.com/sub"
        )
    assert len(calls) == 1


def test_cross_origin_redirect_drops_device_credentials(monkeypatch):
    import requests

    from src.sub.updater import SubscriptionUpdater

    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["headers"])
        response = requests.Response()
        response.status_code = 302 if len(calls) == 1 else 200
        response.headers["Location"] = "https://other.example/sub"
        response._content = b"ok"
        response._content_consumed = True
        return response

    monkeypatch.setattr("src.sub.updater.pinned_get", get)
    assert (
        SubscriptionUpdater()
        ._fetch_once(
            "https://example.com/sub",
            {"User-Agent": "test", "Authorization": "secret", "X-HWID": "secret"},
            True,
        )
        .content
        == "ok"
    )
    assert calls[1] == {"User-Agent": "test"}


def test_stream_limit_stops_before_reading_remaining_body(monkeypatch):
    from unittest.mock import Mock

    from src.sub.errors import SubscriptionTooLargeError
    from src.sub.updater import SubscriptionUpdater

    monkeypatch.setattr("src.sub.updater.MAX_RESPONSE_SIZE", 3)
    response = Mock()
    response.status_code = 200

    def body(**kwargs):
        yield b"1234"
        pytest.fail("Must stop consuming oversized body")

    response.iter_content = body
    monkeypatch.setattr("src.sub.updater.pinned_get", lambda *_a, **_kw: response)
    with pytest.raises(SubscriptionTooLargeError):
        SubscriptionUpdater().fetch("https://example.com/sub")
    response.close.assert_called_once()


@pytest.mark.parametrize("through_proxy", [False, True])
def test_real_tls_pinned_ip_retains_hostname_and_certificate_verification(tmp_path, through_proxy):
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from src.sub.url_policy import pinned_get

    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"tls ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    sni = []
    context.set_servername_callback(lambda _sock, name, _ctx: sni.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"https://localhost:{server.server_port}/sub"
    proxy_server = None
    proxy_thread = None
    connected = []
    proxies = None
    if through_proxy:
        import select
        import socket

        class Proxy(BaseHTTPRequestHandler):
            def do_CONNECT(self):
                connected.append(self.path)
                host, port = self.path.rsplit(":", 1)
                upstream = socket.create_connection((host.strip("[]"), int(port)), timeout=3)
                try:
                    self.send_response(200)
                    self.end_headers()
                    while True:
                        ready, _, _ = select.select([self.connection, upstream], [], [], 3)
                        if not ready:
                            break
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is self.connection else self.connection).sendall(
                                data
                            )
                finally:
                    upstream.close()

            def log_message(self, *args):
                pass

        proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
        proxy_thread.start()
        proxies = {"https": f"http://127.0.0.1:{proxy_server.server_port}"}
    try:
        response = pinned_get(
            url, headers={}, timeout=3, verify=str(cert), exceptions=[url], proxies=proxies
        )
        try:
            assert response.content == b"tls ok"
            assert sni == ["localhost"]
            if through_proxy:
                import ipaddress

                assert ipaddress.ip_address(connected[0].rsplit(":", 1)[0].strip("[]"))
        finally:
            response.close()
            response._subscription_session.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if proxy_server:
            proxy_server.shutdown()
            proxy_server.server_close()
            proxy_thread.join(timeout=3)
