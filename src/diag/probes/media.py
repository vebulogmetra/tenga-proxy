"""Публичный фрагмент медиа: порт PublicMediaProbe.kt.

Без учётной записи и cookies, адреса не сохраняются. Разбор намеренно узкий: изменившийся
ответ сайта не даёт вывода, а не ложный отказ.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget, is_public_address
from src.diag.models import (
    AddressFamily,
    DiagnosticFailure,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)
from src.diag.probes.https import family_of
from src.diag.probes.limits import (
    MEDIA_BYTES,
    TELEGRAM_PAGE_BYTES,
    YOUTUBE_PAGE_BYTES,
    media_request_timeout_s,
    media_total_timeout_s,
)
from src.diag.probes.support import (
    HttpResponse,
    ProbeContext,
    TunnelEndpoint,
    classify,
    elapsed_since,
    https_exchange,
)

YOUTUBE_SOURCES = (
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
)
TELEGRAM_SOURCES = ("https://t.me/telegram/319",)
_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_OG_IMAGE = re.compile(r"property\s*=\s*[\"']og:image[\"']", re.IGNORECASE)
_CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_TELESCOPE = re.compile(r"cdn[0-9]+\.telesco\.pe")
_PLAYER = re.compile(r"ytInitialPlayerResponse\s*=\s*")
_INCONCLUSIVE = frozenset(
    {
        DiagnosticFailure.UNSAFE_ADDRESS,
        DiagnosticFailure.TLS_CERTIFICATE,
        DiagnosticFailure.SYSTEM_RESTRICTED,
        DiagnosticFailure.IO,
    }
)


def _safe(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and not parts.username
        and not parts.password
        and not parts.fragment
        and bool(parts.hostname)
        and url.isascii()
        and not any(ch.isspace() for ch in url)
        and len(url) <= 8192
    )


def telegram_image(html: str) -> str | None:
    tag = next((m.group(0) for m in _META.finditer(html) if _OG_IMAGE.search(m.group(0))), None)
    match = _CONTENT.search(tag) if tag else None
    if match is None:
        return None
    url = match.group(1).replace("&amp;", "&")
    if _safe(url) and _TELESCOPE.fullmatch(urlsplit(url).hostname or ""):
        return url
    return None


def _player_json(html: str) -> dict | None:
    marker = _PLAYER.search(html)
    if marker is None or html[marker.end() : marker.end() + 1] != "{":
        return None
    depth = 0
    quoted = escaped = False
    for index in range(marker.end(), len(html)):
        ch = html[index]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(html[marker.end() : index + 1])
                except ValueError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def youtube_video(html: str) -> str | None:
    player = _player_json(html)
    if player is None:
        return None
    playability = player.get("playabilityStatus")
    data = player.get("streamingData")
    if not isinstance(playability, dict) or playability.get("status") != "OK":
        return None
    if not isinstance(data, dict):
        return None
    for key in ("formats", "adaptiveFormats"):
        formats = data.get(key)
        for item in formats if isinstance(formats, list) else ():
            if not isinstance(item, dict):
                continue
            mime = item.get("mimeType")
            url = item.get("url")
            if (
                isinstance(mime, str)
                and mime.startswith("video/")
                and isinstance(url, str)
                and _safe(url)
                and (urlsplit(url).hostname or "").endswith(".googlevideo.com")
            ):
                return url
    return None


def is_image(data: bytes, content_type: str) -> bool:
    return (
        len(data) >= 512
        and content_type.startswith("image/")
        and (
            data[:3] == b"\xff\xd8\xff"
            or data[:8] == b"\x89PNG\r\n\x1a\n"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        )
    )


def is_video(data: bytes, content_type: str) -> bool:
    return (
        len(data) >= 1024
        and content_type.startswith("video/")
        and (data[4:8] == b"ftyp" or data[:4] == b"\x1a\x45\xdf\xa3")
    )


def probe_media(
    context: ProbeContext,
    id: str,
    target: DiagnosticTarget,
    route: ProbeRoute,
    address: str | None,
    resolve: Callable[[str, AddressFamily], tuple[str, ...]],
    proxy: TunnelEndpoint | None = None,
) -> ProbeObservation:
    if target.purpose not in (DiagnosticPurpose.TELEGRAM_MEDIA, DiagnosticPurpose.YOUTUBE_VIDEO):
        raise ValueError("not a media target")
    youtube = target.purpose is DiagnosticPurpose.YOUTUBE_VIDEO
    started = time.monotonic()
    family = family_of(address) if address else None
    total = media_total_timeout_s(route)
    state = {"received": 0, "stage": "source"}

    def result(status, failure=None, code=None, detail=None) -> ProbeObservation:
        evidence = {
            "transport": "https",
            "coverage": "public-video-fragment" if youtube else "public-image-fragment",
            "receivedBytes": str(state["received"]),
            "mediaStage": state["stage"],
            "responseMatched": str(status is ProbeStatus.SUCCESS).lower(),
        }
        if detail:
            evidence["mediaDetail"] = detail
        return ProbeObservation(
            id, target.id, route, ProbeStage.HTTP, status,
            elapsed_ms=elapsed_since(started), failure_code=failure, address_family=family,
            http_status=code, evidence=evidence,
        )  # fmt: skip

    def fetch(url: str, limit: int, fragment: bool = False) -> HttpResponse:
        parts = urlsplit(url)
        host = parts.hostname or ""
        pinned = None
        if route is ProbeRoute.DIRECT:
            candidates = (address,) if host == target.hostname else resolve(host, family)
            if not candidates:
                raise OSError("no media address")
            if not all(c and is_public_address(c) and family_of(c) is family for c in candidates):
                raise ValueError("unsafe media address")
            pinned = candidates[0]
        headers = {
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "User-Agent": "Mozilla/5.0",
        }
        if fragment:
            headers["Range"] = f"bytes=0-{limit - 1}"
        remaining = total - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("media deadline")
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        response = https_exchange(
            context,
            hostname=host,
            path=path,
            address=pinned,
            proxy=proxy,
            headers=headers,
            timeout=min(media_request_timeout_s(route), remaining),
            read_limit=lambda status, _: limit if status in (200, 206) else 0,
        )
        state["received"] += len(response.body)
        return response

    try:
        sources = YOUTUBE_SOURCES if youtube else TELEGRAM_SOURCES
        # Обе страницы вместе укладываются в резерв бюджета: запасной источник его не удваивает.
        page_limit = YOUTUBE_PAGE_BYTES // len(sources) if youtube else TELEGRAM_PAGE_BYTES
        selected = None
        last_code = None
        for source in sources:
            page = fetch(source, page_limit)
            last_code = page.status
            if not 200 <= page.status <= 299:
                continue
            html = page.body.decode("utf-8", "replace")
            selected = youtube_video(html) if youtube else telegram_image(html)
            if selected:
                break
        if selected is None:
            if last_code is None or not 200 <= last_code <= 299:
                return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.HTTP_REJECTED, last_code)
            return result(
                ProbeStatus.INCONCLUSIVE,
                DiagnosticFailure.UNEXPECTED_RESPONSE,
                detail="media-url-unavailable",
            )
        state["stage"] = "media"
        media = fetch(selected, MEDIA_BYTES, fragment=True)
        if media.status not in (200, 206):
            return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.HTTP_REJECTED, media.status)
        check = is_video if youtube else is_image
        if check(media.body, media.content_type):
            return result(ProbeStatus.SUCCESS, None, media.status)
        return result(
            ProbeStatus.INCONCLUSIVE,
            DiagnosticFailure.UNEXPECTED_RESPONSE,
            media.status,
            "media-format-unexpected",
        )
    except ValueError:
        return result(ProbeStatus.INCONCLUSIVE, DiagnosticFailure.UNSAFE_ADDRESS)
    except OSError as error:
        failure = classify(error, under_tun=context.under_tun)
        status = ProbeStatus.INCONCLUSIVE if failure in _INCONCLUSIVE else ProbeStatus.FAILURE
        return result(status, failure)
