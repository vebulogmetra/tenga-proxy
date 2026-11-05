"""Экспорт отчёта схемы 2: порт DiagnosticReportRedactor.kt.

Схема перечисляет поля явно: адреса, живые контексты и произвольные строки в файл не попадут,
что бы ни оказалось в наблюдении. Поле `platform` добавлено на десктопе.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from src.core.platform_info import IS_WINDOWS
from src.diag.assess import recommendations as rec
from src.diag.models import DiagnosticReport

SCHEMA_VERSION = 2
MAX_OBSERVATIONS = 1024
MAX_BYTES = 1024 * 1024
MAX_FINDINGS = 128
_CATALOG = re.compile(r"[0-9]{1,12}")
_APP = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}")
_NUMBER = re.compile(r"[0-9]{1,9}")
_BOOL = frozenset({"true", "false"})
_ALLOWED = {
    "validated": _BOOL,
    "captivePortal": _BOOL,
    "responseMatched": _BOOL,
    "catalogStale": _BOOL,
    "sharedAnswer": _BOOL,
    "placementGroup": frozenset({"fastly", "cloudflare", "google", "github", "yandex", "vk"}),
    "dohOverlap": frozenset({"full", "partial", "none", "unknown"}),
    "privateDns": frozenset({"off", "opportunistic", "strict", "unknown"}),
    "resolver": frozenset(
        {"system", "cloudflare-doh", "google-doh", "cloudflare-dns", "google-dns"}
    ),
    "tlsVersion": frozenset({"TLSv1", "TLSv1.1", "TLSv1.2", "TLSv1.3"}),
    "transport": frozenset({"https", "mtproto-https", "udp", "tcp", "quic"}),
    "alpn": frozenset({"http/1.1", "h2", "h3"}),
    "coverage": frozenset(
        {
            "family-query", "combined-query-family-filter", "system-path",
            "independent-bootstrap", "http3", "dns-udp", "dns-tcp", "dns-udp-truncated",
            "dns-tcp-truncated", "robots-response", "web-challenge", "public-static-only",
            "mtproto-first-exchange", "known-response", "https-response", "web-entry-only",
            "public-image-fragment", "public-video-fragment", "answer-consistency",
            "dns-identity", "dns-nxdomain",
        }
    ),
    "mediaStage": frozenset({"source", "media"}),
    "mediaDetail": frozenset({"media-url-unavailable", "media-format-unexpected"}),
}  # fmt: skip
_NUMERIC = frozenset(
    {"receivedBytes", "sampleCount", "medianMs", "dnsMs", "tcpMs", "tlsMs", "headersMs", "bodyMs"}
)
_PUBLIC_TARGETS = frozenset(
    {
        "mozilla-success", "cloudflare-trace", "telegram-web", "instagram-web",
        "telegram-public-media", "youtube-web", "youtube-public-video", "telegram-dc2-https",
        "telegram-dc4-https", "instagram-public-icon", "network", "portal", "control", "ok-web",
        "fastly-web", "github-web", "cloudflare-dns-web", "cloudflare-speed", "google-connect",
        "google-web", "github-api", "yandex-main", "yandex-short", "vk-web", "google-dns",
        "cloudflare-dns",
    }
)  # fmt: skip
_FINDINGS = frozenset(
    {
        "CATALOG_STALE", "CAPTIVE_PORTAL_REPORTED", "SYSTEM_RESTRICTION", "PROXY_AUTH_FAILED",
        "VPN_SESSION_CHANGED", "HTTP_ACCESS_REJECTED", "POSSIBLE_WEB_CHALLENGE",
        "SYSTEM_DNS_FAILED", "DNS_PATH_PROBLEM", "TLS_STAGE_FAILURE", "IPV6_TESTS_FAILED",
        "VPN_PATH_AVAILABLE", "POSSIBLE_ALLOWLIST", "ALLOWLIST_INSUFFICIENT_EVIDENCE",
        "QUIC_TEST_FAILED", "QUIC_NOT_CONFIRMED", "DNS_UDP_PATH_FAILED", "CONTROL_LIMITED",
        "NETWORK_UNVERIFIED",
    }
)  # fmt: skip
_RECOMMENDATIONS = frozenset(
    {
        rec.CHECK_SYSTEM_DNS, rec.OPEN_WIFI_LOGIN, rec.USE_ACTIVE_VPN, rec.TRY_OTHER_PROFILE,
        rec.REPEAT_STABLE_NETWORK, rec.RETRY_LATER, rec.CHECK_SYSTEM_NETWORK,
    }
)  # fmt: skip


def _safe_evidence(key: str, value: str) -> bool:
    if key in _ALLOWED:
        return value in _ALLOWED[key]
    if key in _NUMERIC:
        return bool(_NUMBER.fullmatch(value))
    if key == "dnsRcode":
        return value == "unknown" or (value.isdigit() and int(value) <= 4095)
    return False


def _name(value) -> str | None:
    return None if value is None else value.name


def _export(report: DiagnosticReport, prefix: str, targets: dict[str, str], *, limit: int, causes):
    observations = report.observations[:limit]
    ids = {o.id: f"{prefix}{index}" for index, o in enumerate(observations, start=1)}
    data = {
        "schemaVersion": SCHEMA_VERSION,
        "platform": "windows" if IS_WINDOWS else "linux",
        "algorithmVersion": report.context.algorithm_version,
        "catalogVersion": report.context.catalog_version
        if _CATALOG.fullmatch(report.context.catalog_version)
        else "unknown",
        "appVersion": report.context.app_version
        if _APP.fullmatch(report.context.app_version)
        else "unknown",
        "termination": report.termination.name,
        "section": _name(report.context.section),
        "observations": [
            {
                "id": ids[o.id],
                "target": o.target_id if o.target_id in _PUBLIC_TARGETS else targets[o.target_id],
                "route": o.route.name,
                "stage": o.stage.name,
                "status": o.status.name,
                "attempt": o.attempt,
                "elapsedMs": o.elapsed_ms,
                "failureCode": _name(o.failure_code),
                "addressFamily": _name(o.address_family),
                "httpStatus": o.http_status,
                "evidence": {k: v for k, v in o.evidence.items() if _safe_evidence(k, v)},
            }
            for o in observations
        ],
        "findings": [
            {
                "code": f.code if f.code in _FINDINGS else "UNKNOWN",
                "level": f.level.name,
                "observationIds": [ids[i] for i in f.observation_ids if i in ids],
                "recommendationCodes": list(
                    dict.fromkeys(c for c in f.recommendation_codes if c in _RECOMMENDATIONS)
                ),
            }
            for f in report.findings[:MAX_FINDINGS]
        ],
    }
    if len(report.observations) > limit:
        data["truncated"] = True
    if causes is not None:
        data["causes"] = causes
    return data


def encode_report(report: DiagnosticReport, causes: DiagnosticReport | None = None) -> str:
    extra = causes.observations if causes else ()
    names = dict.fromkeys(o.target_id for o in (*report.observations, *extra))
    # Токены целей общие для обоих отчётов, чтобы их можно было сопоставить.
    targets = {name: f"t{index}" for index, name in enumerate(names, start=1)}
    limit = MAX_OBSERVATIONS
    main_limit = min(limit, len(report.observations))
    nested = None
    if causes is not None:
        nested = _export(causes, "c", targets, limit=limit - main_limit, causes=None)
    text = json.dumps(
        _export(report, "o", targets, limit=main_limit, causes=nested),
        ensure_ascii=False,
        indent=2,
    )
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("diagnostic report is too large")
    return text


def export_filename(report: DiagnosticReport) -> str:
    return f"veblock-diagnostics-{report.context.run_id[:8]}.json"


def write_report(
    path: Path, report: DiagnosticReport, causes: DiagnosticReport | None = None
) -> None:
    """Запись через временный файл: при сбое на месте не окажется половины отчёта."""
    text = encode_report(report, causes)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=".veblock-diag-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
