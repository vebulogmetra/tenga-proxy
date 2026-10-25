"""Subscription destination policy and DNS-pinned HTTP transport."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter


class SubscriptionPolicyError(ValueError):
    """A definitive policy denial; never retry or bypass via another route."""


def _public_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_url(url: str, *, exceptions: Iterable[str] = ()):
    """Validate syntax without doing DNS. Exceptions are exact source URLs."""
    if (
        not isinstance(url, str)
        or len(url) > 8192
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
    ):
        raise SubscriptionPolicyError("Некорректный адрес подписки")
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise SubscriptionPolicyError("Некорректный адрес или порт подписки") from None
    if (
        not host
        or parts.scheme not in ("http", "https")
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port == 0
        or "\\" in url
    ):
        raise SubscriptionPolicyError("Недопустимая структура адреса подписки")
    local = (
        host.lower().rstrip(".") == "localhost"
        or host.lower().rstrip(".").endswith((".localhost", ".local", ".lan", ".internal"))
        or not _public_address(host.rstrip("."))
    )
    if (local or parts.scheme != "https") and url not in exceptions:
        raise SubscriptionPolicyError(
            "Для HTTP или локальной подписки требуется разрешение этого источника в настройках"
        )
    return parts


def resolve_destination(url: str, *, exceptions: Iterable[str] = (), resolver=None):
    parts = validate_url(url, exceptions=exceptions)
    resolver = resolver or socket.getaddrinfo
    records = resolver(
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or (
        url not in exceptions and any(not _public_address(ip) for ip in addresses)
    ):
        raise SubscriptionPolicyError("DNS подписки вернул недопустимый адрес")
    return parts, addresses[0]


class _HostnameAdapter(HTTPAdapter):
    """The pool connects (and CONNECTs through proxies) to an already checked
    numeric address. TLS still uses the original hostname for SNI and trust.

    Имя задаётся менеджерам пулов, а не через `build_connection_pool_key_attributes`:
    того нет до requests 2.32, а deb-пакет работает на системном requests
    (2.31 в Ubuntu 24.04), и там сертификат сверялся бы с IP-адресом.
    """

    def __init__(self, hostname: str):
        self._tls_names = {"server_hostname": hostname, "assert_hostname": hostname}
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs, **self._tls_names)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        return super().proxy_manager_for(proxy, **proxy_kwargs, **self._tls_names)


def pinned_get(url: str, *, headers, timeout, verify, proxies=None, exceptions=()):
    parts, address = resolve_destination(url, exceptions=exceptions)
    numeric_host = f"[{address}]" if ":" in address else address
    authority = numeric_host + (f":{parts.port}" if parts.port else "")
    pinned_url = urlunsplit(parts._replace(netloc=authority))
    session = requests.Session()
    session.trust_env = False
    adapter = _HostnameAdapter(parts.hostname)
    session.mount("https://", adapter)
    request_headers = dict(headers)
    request_headers["Host"] = parts.netloc
    try:
        response = session.get(
            pinned_url,
            headers=request_headers,
            timeout=timeout,
            verify=verify,
            proxies=proxies or {},
            allow_redirects=False,
            stream=True,
        )
    except Exception:
        session.close()
        raise
    # Caller must close both streamed response and its owning connection pool.
    response._subscription_session = session
    return response
