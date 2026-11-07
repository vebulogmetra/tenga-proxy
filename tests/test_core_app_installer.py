"""Загрузка установщика: loopback-сервер, прокси, перенаправления, сверка, очистка."""

from __future__ import annotations

import hashlib
import http.server
import threading

import pytest
import requests

from src.core import app_installer
from src.core.app_installer import (
    InstallerCorruptError,
    InstallerDownloadError,
    download_installer,
    remove_stale_downloads,
    verify_installer,
)

PAYLOAD = bytes(range(256)) * 1024
DIGEST = "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def server():
    """/setup.exe — файл; /redirect — переход на него; /short и /long — не тот размер."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/setup.exe")
                self.end_headers()
                return
            if self.path == "/missing":
                self.send_response(404)
                self.end_headers()
                return
            body = {"/setup.exe": PAYLOAD, "/short": PAYLOAD[:-100], "/long": PAYLOAD + b"x"}[
                self.path
            ]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size):
        yield self._body

    def close(self):
        pass


def test_download_follows_redirect_checks_hash_and_reports_progress(server, tmp_path):
    seen = []

    path = download_installer(
        f"{server}/redirect",
        len(PAYLOAD),
        DIGEST,
        directory=tmp_path,
        progress=lambda done, total: seen.append((done, total)),
    )

    assert path.parent == tmp_path
    assert path.name.startswith("veblock-") and path.name.endswith("-setup.exe")
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert {total for _done, total in seen} == {len(PAYLOAD)}


@pytest.mark.parametrize(
    ("route", "error"),
    [
        ("/short", InstallerCorruptError),
        ("/long", InstallerCorruptError),
        ("/missing", InstallerDownloadError),
    ],
)
def test_bad_file_is_removed(server, tmp_path, route, error):
    with pytest.raises(error):
        download_installer(f"{server}{route}", len(PAYLOAD), DIGEST, directory=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_wrong_digest_is_corrupt(server, tmp_path):
    with pytest.raises(InstallerCorruptError):
        download_installer(
            f"{server}/setup.exe", len(PAYLOAD), "sha256:" + "0" * 64, directory=tmp_path
        )

    assert list(tmp_path.iterdir()) == []


def test_connection_failure_is_a_download_error(tmp_path):
    with pytest.raises(InstallerDownloadError):
        download_installer("http://127.0.0.1:9/setup.exe", len(PAYLOAD), DIGEST, directory=tmp_path)


def test_proxy_is_tried_first_then_direct(tmp_path):
    calls = []

    def open_url(url, *, proxies):
        calls.append(proxies)
        if proxies:
            raise requests.ConnectionError("proxy down")
        return FakeResponse(200, body=PAYLOAD)

    path = download_installer(
        "https://github.com/x",
        len(PAYLOAD),
        DIGEST,
        directory=tmp_path,
        proxy_url="http://127.0.0.1:2081",
        open_url=open_url,
    )

    assert calls == [{"http": "http://127.0.0.1:2081", "https": "http://127.0.0.1:2081"}, None]
    assert path.read_bytes() == PAYLOAD


def test_redirect_to_http_is_refused(tmp_path):
    def open_url(url, *, proxies):
        return FakeResponse(302, {"Location": "http://github.com/x"})

    with pytest.raises(InstallerDownloadError, match="HTTP"):
        download_installer(
            "https://github.com/x", len(PAYLOAD), DIGEST, directory=tmp_path, open_url=open_url
        )

    assert list(tmp_path.iterdir()) == []


def test_too_many_redirects_is_a_download_error(tmp_path):
    def open_url(url, *, proxies):
        return FakeResponse(302, {"Location": "https://github.com/x"})

    with pytest.raises(InstallerDownloadError, match="перенаправлений"):
        download_installer(
            "https://github.com/x", len(PAYLOAD), DIGEST, directory=tmp_path, open_url=open_url
        )


def test_size_limit_rejects_huge_assets_before_the_network(tmp_path):
    def never(*_args, **_kwargs):
        pytest.fail("сеть не нужна")

    with pytest.raises(InstallerCorruptError):
        download_installer(
            "https://github.com/x",
            app_installer.MAX_INSTALLER_SIZE + 1,
            DIGEST,
            directory=tmp_path,
            open_url=never,
        )


def test_verify_installer_checks_size_then_hash(tmp_path):
    path = tmp_path / "setup.exe"
    path.write_bytes(PAYLOAD)

    verify_installer(path, len(PAYLOAD), DIGEST)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD) - 1, DIGEST)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD), "sha256:" + "0" * 64)
    with pytest.raises(InstallerCorruptError):
        verify_installer(path, len(PAYLOAD), "md5:" + "0" * 32)


def test_stale_downloads_are_removed(tmp_path):
    stale = tmp_path / "veblock-old-setup.exe"
    stale.write_bytes(b"x")

    assert remove_stale_downloads(tmp_path) == [stale]
    assert not stale.exists()
    assert remove_stale_downloads(tmp_path / "missing") == []


def test_download_dir_lives_in_temp():
    assert app_installer.download_dir().name == "veblock-update"
