# Диагностика сети на десктопе (Linux, Windows): план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Перенести фичу «Диагностика сети» из Android-версии Veblock в десктопный клиент: тот же алгоритм (15), каталог целей (v6), вердикты, тексты и экспорт схемы 2; окно в GTK и Qt; логика без тулкита.

**Architecture:** Новый пакет `src/diag/` — порт 1:1 доменного слоя Android (`domain/diagnostics/*.kt`, `data/diagnostics/*.kt`): модели, каталог, план фаз 0–8, планировщик с бюджетами, пробы на `socket`/`ssl`/`requests`, оценщики, итог, экспорт. Прямые пробы при TUN привязываются к физическому интерфейсу через новый фасад `src/sys/netbind.py`; туннельные идут через health-inbound текущего сеанса. Экран — `DiagnosticsSession` и `DiagnosticsView` в `src/ui/logic/`, окна в `src/ui/dialogs/` и `src/ui/qt/dialogs/`. Дизайн: `docs/plans/2026-11-05-network-diagnostics-desktop-design.md`.

**Tech Stack:** Python 3.11 (`socket`, `ssl`, `struct`, `threading`, `concurrent.futures`, `json`), requests, pytest, GTK 4/libadwaita, PySide6. Эталон — Kotlin-код Android в `../tenga-proxy-android/app/src/main/java/com/wingeon/app/{domain,data}/diagnostics/` и его тесты в `app/src/test/java/com/wingeon/app/{domain,data}/diagnostics/`.

**Правила для исполнителя:**
- Эталон — Kotlin. Для каждого модуля открой указанный `.kt` и перенеси логику дословно: те же имена enum, коды, пороги, порядок приоритетов, идентификаторы наблюдений. Тесты из парного `*Test.kt` переноси как сценарии pytest; имена тестов — по смыслу, на английском, как в репозитории.
- Публичную сеть в тестах не трогать: только loopback-серверы из `tests/support/diag.py`. Любой тест, который может уйти в интернет, — ошибка плана.
- На машине разработчика живой сеанс TUN (`xray0`). xray с TUN не запускать, `nft` и маршруты не трогать.
- Команды тестов: `uv run pytest <файл> -q -p no:cacheprovider --no-cov`. Линтер перед коммитом: `uv run python cli.py lint-all`.
- Стиль: строка 100, docstring и комментарии по-русски и о «почему», тексты интерфейса по-русски, слово «Сервер», а не «профиль». Dataclass'ы замороженные, коллекции в них — `tuple`.
- Коммиты маленькие, в стиле репозитория: `feat(diag): …`, `feat(sys): …`, `feat(ui): …`, `test(diag): …`, `docs: …`.
- Kotlin `require(...)` → `ValueError` в `__post_init__`; `Map<String,String>` → `Mapping[str, str]` с копированием в `dict` в `__post_init__` через `object.__setattr__`.

---

## Этап 0. Подготовка

### Task 0.1: Каталог целей и общие тестовые серверы

**Files:**
- Create: `assets/diagnostics/targets.json` (копия Android)
- Create: `assets/diagnostics/placements.json` (копия Android)
- Create: `tests/support/diag.py`
- Create: `tests/support/certs/README.md`
- Modify: `core/scripts/build_deb.sh:59-62` (ничего удалять не нужно: `assets/` копируется целиком; добавить проверку наличия файла после строки 78)
- Modify: `tests/test_packaging_spec.py` (spec уже собирает `assets/**`; добавить проверку, что в `datas` есть `assets/diagnostics`)
- Test: `tests/test_packaging_spec.py`, `tests/test_cli_build.py`

**Step 1: Скопировать каталог**

```bash
mkdir -p assets/diagnostics
cp ../tenga-proxy-android/app/src/main/assets/diagnostics/targets.json assets/diagnostics/
cp ../tenga-proxy-android/app/src/main/assets/diagnostics/placements.json assets/diagnostics/
python -c "import json;json.load(open('assets/diagnostics/targets.json'));json.load(open('assets/diagnostics/placements.json'))"
```

**Step 2: Написать падающий тест на сборку**

В `tests/test_packaging_spec.py` добавить:

```python
def test_spec_bundles_diagnostics_catalog():
    datas = _spec_datas()  # уже есть помощник, читающий datas из spec; если нет — см. соседние тесты
    assert any(dest == "assets/diagnostics" for _src, dest in datas)
```

В `tests/test_cli_build.py` (где проверяется содержимое deb-скрипта) добавить:

```python
def test_build_deb_checks_diagnostics_catalog():
    script = Path("core/scripts/build_deb.sh").read_text(encoding="utf-8")
    assert "assets/diagnostics/targets.json" in script
```

**Step 3: Запустить, убедиться, что падают**

Run: `uv run pytest tests/test_packaging_spec.py tests/test_cli_build.py -q -p no:cacheprovider --no-cov`
Expected: два FAIL.

**Step 4: Реализовать**

В `core/scripts/build_deb.sh` после проверки `index.theme` (строка 78):

```bash
    [ -f "$PKG_ROOT/$LIB_DIR/assets/diagnostics/targets.json" ] \
        || { echo "Каталог диагностики не попал в пакет" >&2; exit 1; }
```

В spec `datas` уже обходит `assets` рекурсивно (строка 13); если тест падает — добавить `assets/diagnostics/*.json` явно по образцу соседних записей.

**Step 5: Тестовые серверы**

`tests/support/diag.py` — общие помощники для всех тестов проб:

```python
"""Loopback-серверы для тестов проб: HTTPS, DNS по UDP/TCP. В интернет не ходят."""

from __future__ import annotations

import socket
import ssl
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CERT_DIR = Path(__file__).parent / "certs"


def make_cert(tmp_path: Path, hostname: str = "localhost") -> tuple[Path, Path]:
    """Самоподписанный сертификат на hostname через openssl (есть в CI и у разработчика)."""
    import subprocess

    key, cert = tmp_path / "key.pem", tmp_path / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={hostname}",
         "-addext", f"subjectAltName=DNS:{hostname},IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    return key, cert


class ScriptedHttpsServer:
    """HTTPS на loopback: ответы задаются по пути; считает запросы."""

    def __init__(self, tmp_path: Path, responses: dict[str, tuple[int, bytes, dict[str, str]]]):
        key, cert = make_cert(tmp_path)
        self.cert = cert
        self.requests: list[tuple[str, dict[str, str]]] = []
        responses_ref = responses
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):  # noqa: N802
                server.requests.append((self.path, dict(self.headers)))
                status, body, headers = responses_ref.get(self.path, (404, b"", {}))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def client_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(cafile=str(self.cert))
        return ctx

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeDnsServer:
    """UDP и TCP DNS на loopback: `answers[(qname, qtype)] = (rcode, [rdata bytes])`.

    `truncate_udp=True` отдаёт по UDP ответ с TC=1 и без записей — проверка перехода на TCP.
    """

    def __init__(self, answers: dict[tuple[str, int], tuple[int, list[bytes]]], *, truncate_udp=False):
        self.answers = answers
        self.truncate_udp = truncate_udp
        self.queries: list[tuple[str, str, int]] = []  # (transport, qname, qtype)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.bind(("127.0.0.1", 0))
        self.tcp.listen()
        self.port_udp = self.udp.getsockname()[1]
        self.port_tcp = self.tcp.getsockname()[1]
        self._stop = threading.Event()
        threading.Thread(target=self._serve_udp, daemon=True).start()
        threading.Thread(target=self._serve_tcp, daemon=True).start()

    # Разбор запроса и сборка ответа используют src.diag.probes.dns_wire — после Task 3.1
    def _reply(self, transport: str, data: bytes) -> bytes:
        from src.diag.probes import dns_wire

        query = dns_wire.parse_query(data)
        self.queries.append((transport, query.name, query.qtype))
        if transport == "udp" and self.truncate_udp:
            return dns_wire.build_response(query, rcode=0, answers=[], truncated=True)
        rcode, rdata = self.answers.get((query.name, query.qtype), (3, []))
        return dns_wire.build_response(query, rcode=rcode, answers=rdata)

    def _serve_udp(self):
        self.udp.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data, addr = self.udp.recvfrom(4096)
            except socket.timeout:
                continue
            self.udp.sendto(self._reply("udp", data), addr)

    def _serve_tcp(self):
        self.tcp.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.tcp.accept()
            except socket.timeout:
                continue
            with conn:
                length = struct.unpack("!H", conn.recv(2))[0]
                data = conn.recv(length)
                reply = self._reply("tcp", data)
                conn.sendall(struct.pack("!H", len(reply)) + reply)

    def close(self):
        self._stop.set()
        self.udp.close()
        self.tcp.close()
```

`tests/support/certs/README.md`: «Сертификаты генерируются на лету `make_cert`; в репозитории ключей нет».

**Step 6: Проверить и закоммитить**

Run: `uv run pytest tests/test_packaging_spec.py tests/test_cli_build.py -q -p no:cacheprovider --no-cov`
Expected: PASS.

```bash
git add assets/diagnostics tests/support/diag.py tests/support/certs core/scripts/build_deb.sh tests/test_packaging_spec.py tests/test_cli_build.py
git commit -m "feat(diag): каталог целей диагностики и loopback-серверы для тестов"
```

---

## Этап 1. Домен: модели, каталог, план

### Task 1.1: Модели отчёта

**Files:**
- Create: `src/diag/__init__.py` (пустой с docstring «Диагностика сети: порт Android-алгоритма 15»)
- Create: `src/diag/models.py`
- Test: `tests/test_diag_models.py`
- Эталон: `domain/diagnostics/DiagnosticModels.kt` (113 строк), `DiagnosticRequest.kt`, `DiagnosticModelsTest.kt`

**Step 1: Написать падающие тесты**

```python
import pytest

from src.diag.models import (
    DiagnosticFailure,
    DiagnosticRequest,
    DiagnosticSection,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
)


def obs(**kw):
    base = dict(id="o1", target_id="t", route=ProbeRoute.DIRECT, stage=ProbeStage.HTTP,
                status=ProbeStatus.SUCCESS)
    base.update(kw)
    return ProbeObservation(**base)


def test_observation_rejects_unknown_evidence_key():
    with pytest.raises(ValueError):
        obs(evidence={"ipAddress": "1.2.3.4"})


def test_observation_rejects_long_or_control_values():
    with pytest.raises(ValueError):
        obs(evidence={"alpn": "x" * 129})
    with pytest.raises(ValueError):
        obs(evidence={"alpn": "h2\n"})


def test_observation_attempt_bounds():
    with pytest.raises(ValueError):
        obs(attempt=0)
    with pytest.raises(ValueError):
        obs(attempt=4)
    assert obs(attempt=3).attempt == 3


def test_observation_http_status_bounds():
    with pytest.raises(ValueError):
        obs(http_status=99)
    assert obs(http_status=204).http_status == 204


def test_request_limits_match_android():
    r = DiagnosticRequest()
    assert (r.deadline_ms, r.max_attempts, r.max_payload_bytes) == (120_000, 384, 8 * 1024 * 1024)
    with pytest.raises(ValueError):
        DiagnosticRequest(deadline_ms=120_001)
    with pytest.raises(ValueError):
        DiagnosticRequest(detail_target_ids=tuple(f"t{i}" for i in range(33)))


def test_sections_phases():
    assert DiagnosticSection.ALLOWLIST.phases == frozenset({0, 1, 2, 3})
    assert DiagnosticSection.SERVICES.phases == frozenset({0, 4, 5, 6})
    assert DiagnosticSection.DNS.phases == frozenset({0, 1, 4, 7})
    assert DiagnosticSection.DETAILS.phases == frozenset({0, 1, 4, 8})


def test_failure_codes_are_the_android_set():
    assert {f.name for f in DiagnosticFailure} >= {
        "USER_CANCELLED", "NETWORK_CHANGED", "VPN_SESSION_CHANGED", "DEADLINE", "BUDGET",
        "NO_NETWORK", "AMBIGUOUS_NETWORK", "SYSTEM_RESTRICTED", "DNS_FAILED", "TIMEOUT",
        "CONNECTION_REFUSED", "CONNECTION_RESET", "TLS_CERTIFICATE", "TLS_FAILED",
        "HTTP_REJECTED", "UNEXPECTED_RESPONSE", "BODY_LIMIT", "UNSAFE_ADDRESS",
        "PROXY_UNAVAILABLE", "PROXY_AUTH", "CONTROL_UNAVAILABLE", "NOT_IMPLEMENTED", "IO",
        "DNS_TRUNCATED", "QUIC_FALLBACK", "QUIC_FAILED", "ENGINE_UNAVAILABLE",
        "TRANSPORT_UNSUPPORTED",
    }
```

**Step 2: Запустить**

Run: `uv run pytest tests/test_diag_models.py -q -p no:cacheprovider --no-cov`
Expected: FAIL, `ModuleNotFoundError: src.diag`.

**Step 3: Реализовать `src/diag/models.py`**

```python
"""Модели отчёта диагностики: порт DiagnosticModels.kt и DiagnosticRequest.kt.

Имена enum и коды совпадают с Android: отчёты с обеих платформ читает одна поддержка.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
ALGORITHM_VERSION = 15

MAX_DEADLINE_MS = 120_000
MAX_ATTEMPTS = 384
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_DETAIL_TARGETS = 32

EVIDENCE_KEYS = frozenset({
    "placementGroup", "coverage", "resolver", "validated", "captivePortal",
    "networkType", "vpnActive", "privateDns", "tlsVersion", "alpn", "responseMatched",
    "catalogStale", "receivedBytes", "sampleCount", "medianMs", "errorRatio", "transport",
    "mediaStage", "mediaDetail", "dnsRcode", "dnsMs", "tcpMs", "tlsMs", "headersMs", "bodyMs",
    "dohOverlap", "sharedAnswer",
})


class ProbeRoute(enum.Enum):
    DIRECT = "DIRECT"
    ACTIVE_TUNNEL = "ACTIVE_TUNNEL"


class ProbeStage(enum.Enum):
    NETWORK = "NETWORK"
    DNS = "DNS"
    TCP = "TCP"
    TLS = "TLS"
    HTTP = "HTTP"
    UDP = "UDP"
    QUIC = "QUIC"
    QUALITY = "QUALITY"


class ProbeStatus(enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    INCONCLUSIVE = "INCONCLUSIVE"


class AddressFamily(enum.Enum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"


class EvidenceLevel(enum.Enum):
    OBSERVED = "OBSERVED"
    LIKELY = "LIKELY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DiagnosticFailure(enum.Enum):
    USER_CANCELLED = "USER_CANCELLED"
    NETWORK_CHANGED = "NETWORK_CHANGED"
    VPN_SESSION_CHANGED = "VPN_SESSION_CHANGED"
    DEADLINE = "DEADLINE"
    BUDGET = "BUDGET"
    NO_NETWORK = "NO_NETWORK"
    AMBIGUOUS_NETWORK = "AMBIGUOUS_NETWORK"
    SYSTEM_RESTRICTED = "SYSTEM_RESTRICTED"
    DNS_FAILED = "DNS_FAILED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    CONNECTION_RESET = "CONNECTION_RESET"
    TLS_CERTIFICATE = "TLS_CERTIFICATE"
    TLS_FAILED = "TLS_FAILED"
    HTTP_REJECTED = "HTTP_REJECTED"
    UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE"
    BODY_LIMIT = "BODY_LIMIT"
    UNSAFE_ADDRESS = "UNSAFE_ADDRESS"
    PROXY_UNAVAILABLE = "PROXY_UNAVAILABLE"
    PROXY_AUTH = "PROXY_AUTH"
    CONTROL_UNAVAILABLE = "CONTROL_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    IO = "IO"
    DNS_TRUNCATED = "DNS_TRUNCATED"
    QUIC_FALLBACK = "QUIC_FALLBACK"
    QUIC_FAILED = "QUIC_FAILED"
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    TRANSPORT_UNSUPPORTED = "TRANSPORT_UNSUPPORTED"


class DiagnosticTermination(enum.Enum):
    COMPLETED = "COMPLETED"
    USER_CANCELLED = "USER_CANCELLED"
    NETWORK_CHANGED = "NETWORK_CHANGED"
    DEADLINE = "DEADLINE"
    BACKGROUND = "BACKGROUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class DiagnosticSection(enum.Enum):
    """Какие фазы плана выполняет проверка: вся или одна карточка."""

    ALL = frozenset(range(9))
    ALLOWLIST = frozenset({0, 1, 2, 3})
    SERVICES = frozenset({0, 4, 5, 6})
    DNS = frozenset({0, 1, 4, 7})
    DETAILS = frozenset({0, 1, 4, 8})

    @property
    def phases(self) -> frozenset[int]:
        return self.value


def _check_evidence(evidence: Mapping[str, str]) -> dict[str, str]:
    for key, value in evidence.items():
        if key not in EVIDENCE_KEYS:
            raise ValueError(f"evidence key {key!r} is not allowed")
        if len(value) > 128 or any(ch.isspace() and ch != " " or ord(ch) < 32 for ch in value):
            raise ValueError(f"evidence value for {key!r} is too long or has control chars")
    return dict(evidence)


@dataclass(frozen=True)
class ProbeObservation:
    id: str
    target_id: str
    route: ProbeRoute
    stage: ProbeStage
    status: ProbeStatus
    attempt: int = 1
    elapsed_ms: int = 0
    failure_code: DiagnosticFailure | None = None
    address_family: AddressFamily | None = None
    http_status: int | None = None
    evidence: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.target_id.strip():
            raise ValueError("observation needs id and target_id")
        if not 1 <= self.attempt <= 3 or self.elapsed_ms < 0:
            raise ValueError("attempt must be 1..3 and elapsed_ms >= 0")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("http_status out of range")
        object.__setattr__(self, "evidence", _check_evidence(self.evidence))


@dataclass(frozen=True)
class DiagnosticFinding:
    code: str
    level: EvidenceLevel
    observation_ids: tuple[str, ...]
    recommendation_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticRunContext:
    run_id: str
    catalog_version: int
    app_version: str
    section: DiagnosticSection = DiagnosticSection.ALL
    schema_version: int = SCHEMA_VERSION
    algorithm_version: int = ALGORITHM_VERSION

    @staticmethod
    def new_run_id() -> str:
        return uuid.uuid4().hex


@dataclass(frozen=True)
class DiagnosticRequest:
    deadline_ms: int = MAX_DEADLINE_MS
    max_attempts: int = MAX_ATTEMPTS
    max_payload_bytes: int = MAX_PAYLOAD_BYTES
    section: DiagnosticSection = DiagnosticSection.ALL
    detail_target_ids: tuple[str, ...] = ()
    compare_active_tunnel: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.deadline_ms <= MAX_DEADLINE_MS:
            raise ValueError("deadline_ms out of range")
        if not 0 < self.max_attempts <= MAX_ATTEMPTS:
            raise ValueError("max_attempts out of range")
        if not 0 < self.max_payload_bytes <= MAX_PAYLOAD_BYTES:
            raise ValueError("max_payload_bytes out of range")
        if len(self.detail_target_ids) > MAX_DETAIL_TARGETS:
            raise ValueError("too many detail targets")
```

Оценки этапов (`AllowlistAssessment`, `ServiceAssessment`, `DnsAssessment`, `CauseAssessment`) и `DiagnosticReport` добавляются в этом же файле, их поля — из соответствующих Kotlin-файлов оценщиков (Task 4.x дополняют `models.py`, а не создают новые классы отчёта).

**Step 4: Запустить**

Run: `uv run pytest tests/test_diag_models.py -q -p no:cacheprovider --no-cov`
Expected: PASS.

**Step 5: Коммит**

```bash
git add src/diag tests/test_diag_models.py
git commit -m "feat(diag): модели отчёта диагностики сети"
```

### Task 1.2: Каталог и реестр размещений

**Files:**
- Create: `src/diag/catalog.py`
- Test: `tests/test_diag_catalog.py`
- Эталон: `domain/diagnostics/DiagnosticTarget.kt`, `data/diagnostics/DiagnosticCatalogRepository.kt`, `DiagnosticPlacementRegistry.kt`, тесты `DiagnosticCatalogRepositoryTest.kt`, `DiagnosticPlacementRegistryTest.kt`

**Step 1: Тесты**

```python
import ipaddress
import json

import pytest

from src.diag.catalog import (
    RUSSIAN_REFERENCES,
    PlacementRegistry,
    TargetPurpose,
    load_catalog,
)


def test_bundled_catalog_loads_v6():
    catalog = load_catalog()
    assert catalog.version == 6
    assert {t.id for t in catalog.targets} >= {
        "mozilla-success", "cloudflare-trace", "google-web", "yandex-main", "vk-web",
        "telegram-web", "instagram-web", "youtube-web", "youtube-public-video",
    }
    assert catalog.target("google-connect").expected_status == 204


def test_dns_targets_exclude_instagram():
    catalog = load_catalog()
    ids = {t.id for t in catalog.dns_targets()}
    assert "instagram-web" not in ids and "yandex-main" in ids


def test_baseline_groups_are_six():
    catalog = load_catalog()
    groups = {t.placement_group for t in catalog.targets if t.purpose is TargetPurpose.BASELINE}
    assert groups == {"fastly", "cloudflare", "google", "github", "yandex", "vk"}


def test_stale_catalog_is_detected():
    catalog = load_catalog()
    assert not catalog.is_stale(now=catalog.expires_at - 1)
    assert catalog.is_stale(now=catalog.expires_at + 1)


def test_broken_catalog_raises(tmp_path):
    bad = tmp_path / "targets.json"
    bad.write_text(json.dumps({"schemaVersion": 1, "catalogVersion": 6, "targets": [{}]}))
    with pytest.raises(ValueError):
        load_catalog(bad)


def test_placement_registry_verifies_known_prefix():
    registry = PlacementRegistry.load()
    target = load_catalog().target("cloudflare-trace")
    sample = ipaddress.ip_address(registry.sample_address(target.id))  # первый адрес первого префикса
    assert registry.verify(target.id, str(sample))
    assert not registry.verify(target.id, "203.0.113.10")


def test_russian_references():
    assert RUSSIAN_REFERENCES == frozenset({"yandex.ru", "ya.ru", "vk.com", "ok.ru"})
```

**Step 2: Запустить** → FAIL (нет модуля).

**Step 3: Реализовать**

- `TargetPurpose` (BASELINE, TELEGRAM_WEB, TELEGRAM_APP, INSTAGRAM_WEB, INSTAGRAM_MEDIA, TELEGRAM_MEDIA, YOUTUBE_WEB, YOUTUBE_VIDEO, CONTROL), `TargetCoverage` — как в `DiagnosticTarget.kt`.
- `DiagnosticTarget` замороженный dataclass: `id, hostname, placement_group, port=443, path="/", purpose=BASELINE, max_bytes, expected_status, expected_body, families=("ipv4",), coverage`; `origin` = `f"{hostname}:{port}"`.
- `Catalog(version, expires_at, targets)` с `target(id)`, `dns_targets()`, `is_stale(now)`, `by_purpose(*purposes)`.
- `load_catalog(path=None)`: по умолчанию `get_asset_path("diagnostics/targets.json")` из `src.core.config`; разбор как в `DiagnosticCatalogRepository.kt`; поля обязательные → `ValueError` с понятным текстом.
- `PlacementRegistry.load(path=None)` из `placements.json`; `verify(target_id, ip)` — `ipaddress.ip_address(ip) in ipaddress.ip_network(prefix)`; `verified_groups()`; `sample_address(target_id)` — для тестов.
- `RUSSIAN_REFERENCES`.

**Step 4: PASS → коммит** `feat(diag): каталог целей и реестр размещений`

### Task 1.3: План проб: фазы и идентификаторы

**Files:**
- Create: `src/diag/plan.py`
- Test: `tests/test_diag_plan.py`
- Эталон: `data/diagnostics/DiagnosticProbePlan.kt` (207 строк), `domain/diagnostics/ServiceProbePlanner.kt`, тесты `DiagnosticProbePlanTest.kt`, `ServiceProbePlannerTest.kt`

**Step 1: Тесты** (перенести все сценарии из двух `*Test.kt`; ключевые ниже)

```python
from src.diag.catalog import load_catalog
from src.diag.models import DiagnosticRequest, DiagnosticSection, ProbeRoute, ProbeStage
from src.diag.plan import ProbeKind, build_plan


def ids(tasks):
    return [t.observation_id for t in tasks]


def test_full_plan_has_nine_phases_and_only_ipv4():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=True)
    assert set(plan.phases) == set(range(9))
    assert all(t.family == "ipv4" for t in plan.tasks)


def test_phase0_is_network_baseline():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=True)
    assert [t.stage for t in plan.phase(0)] == [ProbeStage.NETWORK]


def test_allowlist_ids_follow_android_pattern():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=False)
    http = [t for t in plan.phase(2) if t.route is ProbeRoute.DIRECT]
    assert "mozilla-success-ipv4-http-1" in ids(http)
    assert "mozilla-success-ipv4-http-2" in ids(plan.phase(3))


def test_tunnel_tasks_only_when_available():
    with_tunnel = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=True)
    without = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=False)
    assert "yandex-main-tunnel" in ids(with_tunnel.tasks)
    assert "yandex-main-tunnel" not in ids(without.tasks)


def test_dns_phase_ids():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=False)
    dns = ids(plan.phase(7))
    assert "yandex-main-ipv4-dns-system" in dns
    assert "yandex-main-ipv4-dns-cloudflare-doh" in dns
    assert "cloudflare-dns-udp-1" in dns and "google-dns-tcp-2" in dns
    assert "cloudflare-dns-identity" in dns and "google-dns-nxdomain" in dns
    assert "instagram-web-ipv4-dns-system" not in dns


def test_sections_select_phases():
    plan = build_plan(load_catalog(), DiagnosticRequest(section=DiagnosticSection.DNS),
                      tunnel_available=False)
    assert set(plan.phases) == {0, 1, 4, 7}


def test_details_section_plans_tcp_and_tls_for_failed_and_controls():
    request = DiagnosticRequest(section=DiagnosticSection.DETAILS,
                                detail_target_ids=("vk-web",), deadline_ms=60_000)
    plan = build_plan(load_catalog(), request, tunnel_available=False)
    phase8 = ids(plan.phase(8))
    assert {"vk-web-tcp-1", "vk-web-tcp-2", "vk-web-tls-1", "vk-web-tls-2"} <= set(phase8)
    for control in ("google-web", "cloudflare-trace", "yandex-main"):
        assert f"{control}-tcp-1" in phase8


def test_payload_reservations_match_android():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=False)
    by_id = {t.observation_id: t for t in plan.tasks}
    assert by_id["yandex-main-ipv4-dns-system"].reserve_bytes == 16_656
    assert by_id["mozilla-success-ipv4-http-1"].reserve_bytes == 1024 + 1
    assert by_id["telegram-public-media-ipv4-http-1"].reserve_bytes == 64 * 1024 + 16 * 1024


def test_plan_has_no_quic_tasks():
    plan = build_plan(load_catalog(), DiagnosticRequest(), tunnel_available=True)
    assert all(t.kind is not ProbeKind.QUIC for t in plan.tasks)
    assert len(plan.tasks) <= 1024
```

**Step 2: FAIL. Step 3: Реализовать**

`ProbeTask(observation_id, target_id, phase, route, stage, kind: ProbeKind, family, attempt, reserve_bytes, timeout_s, extra: Mapping)`; `ProbeKind` = NETWORK, HTTPS, TUNNEL_HTTPS, MEDIA, TELEGRAM_APP, DNS_SYSTEM, DNS_TRANSPORT, DNS_DOH, DNS_IDENTITY, DNS_NXDOMAIN, TCP, TLS. `Plan(tasks)` с `phase(n)`, `phases`. Follow-up правила (tie-break третьей попытки, `-ipv4-dns-system-2`, `-ipv4-dns-consistency`) — функции `follow_ups(observations) -> list[ProbeTask]`, вызываются планировщиком после пакета, как в Kotlin. Таймауты из `DiagnosticTimeouts.kt`: прямой HTTPS 5 с, туннель 15 с, медиа 7/15 и 15/30, DNS 3 с. Фазы и состав — строго по `DiagnosticProbePlan.kt`; QUIC-ветки пропускаются.

**Step 4: PASS → коммит** `feat(diag): план проб по фазам и секциям`

---

## Этап 2. Бюджеты и планировщик

### Task 2.1: Бюджет

**Files:**
- Create: `src/diag/budget.py`
- Test: `tests/test_diag_budget.py`
- Эталон: `DiagnosticBudget.kt`, `DiagnosticBudgetTest.kt`

**Тесты:** резерв попытки до лимита даёт `True`, сверх — `False`; байты резервируются до ввода-вывода и не возвращаются (`release` нет); `remaining_ms(clock)` ≤ 0 после дедлайна; потокобезопасность — 50 потоков по 10 резервов не превышают лимит.

**Реализация:** `DiagnosticBudget(max_attempts, max_payload_bytes, deadline_ms, clock=time.monotonic)` с `threading.Lock`, методами `try_attempt()`, `try_bytes(n)`, `remaining_ms()`, `exhausted` свойство.

Коммит: `feat(diag): бюджеты попыток, байт и срока`

### Task 2.2: Планировщик с отменой и лимитом на origin

**Files:**
- Create: `src/diag/scheduler.py`
- Test: `tests/test_diag_scheduler.py`
- Эталон: `DiagnosticScheduler.kt` (91 строка), `DiagnosticScheduleSession.kt`, `DiagnosticSchedulerTest.kt`

**Тесты (с поддельной пробой `fake_probe(task) -> ProbeObservation`, которая считает одновременные вызовы):**

```python
def test_concurrency_is_four_and_two_per_origin(): ...
def test_phases_run_in_order_and_follow_ups_are_appended(): ...
def test_budget_exhaustion_marks_remaining_skipped_budget(): ...
def test_deadline_cancels_running_and_skips_rest(): ...
def test_cancel_closes_registered_sockets_and_marks_user_cancelled(): ...
def test_probe_exception_becomes_failure_io_not_crash(): ...
def test_batches_are_capped_at_160_tasks(): ...
def test_observation_callback_runs_for_every_task(): ...
```

**Реализация:** `Scheduler(plan, budget, probes: Mapping[ProbeKind, Probe], on_observation, cancel: threading.Event)`; `ThreadPoolExecutor(max_workers=4)`; `dict[origin, threading.BoundedSemaphore(2)]`; `SocketRegistry` (`add(sock)`, `discard(sock)`, `close_all()`), которую пробы получают через `ProbeContext`; задачи с `reserve_bytes`, которые бюджет не даёт — `SKIPPED(BUDGET)`; задачи после дедлайна — `SKIPPED(DEADLINE)`, выполнявшиеся — `CANCELLED(DEADLINE)`; `interrupt(reason: DiagnosticFailure)` для NETWORK_CHANGED/USER_CANCELLED. Результат — `list[ProbeObservation]` и `termination`.

Коммит: `feat(diag): планировщик проб с бюджетами и отменой`

---

## Этап 3. Пробы

### Task 3.1: DNS wire

**Files:**
- Create: `src/diag/probes/__init__.py`, `src/diag/probes/dns_wire.py`
- Test: `tests/test_diag_dns_wire.py`
- Эталон: `probe/DnsWire.kt` (128 строк), `DnsWireTest.kt`

**Тесты:** сборка запроса A с RD и EDNS0 (размер 4096) — байты совпадают с заранее посчитанным образцом; разбор ответа с A-записями и сжатием имён; TXT в классе CH (`id.server`); RCODE NXDOMAIN; флаг TC; отказ на ответ больше 16 КиБ и на чужой ID (`ValueError`); `parse_query`/`build_response` для тестового сервера из Task 0.1.

**Реализация:** `struct`-кодирование; `Question(name, qtype, qclass)`, `DnsMessage(id, rcode, truncated, answers: tuple[Record])`, `Record(name, rtype, rclass, ttl, rdata)`; `build_query(name, qtype, qclass=1, edns=True) -> (id, bytes)`, `parse_response(data, expected_id) -> DnsMessage`, `parse_query`, `build_response`. Константы `TYPE_A=1, TYPE_AAAA=28, TYPE_TXT=16, CLASS_IN=1, CLASS_CH=3`.

Коммит: `feat(diag): кодирование и разбор DNS-сообщений`

### Task 3.2: Классификация ошибок и безопасные адреса

**Files:**
- Create: `src/diag/probes/support.py`
- Test: `tests/test_diag_probe_support.py`
- Эталон: `probe/ProbeSupport.kt`, `data/diagnostics/DiagnosticAddressPolicy.kt`, `ProbeSupportTest.kt`

**Тесты:** `classify(exc)` → таблица из дизайна (timeout, refused, reset, cert, ssl, gaierror, OSError, другое); `is_safe_address("10.0.0.1") is False`, `"0.0.0.0"`, `"127.0.0.1"`, `"169.254.1.1"`, `"224.0.0.1"` небезопасны, `"1.1.1.1"` безопасен; `Stopwatch` возвращает `elapsed_ms ≥ 0`; `ProbeContext(cancel, sockets, bind)`.

Коммит: `feat(diag): классификация ошибок проб и политика адресов`

### Task 3.3: Фасад привязки сокета к интерфейсу

**Files:**
- Create: `src/sys/netbind.py`, `src/sys/linux/netbind.py`, `src/sys/windows/netbind.py`
- Modify: `tests/test_sys_facades.py:11-20` (добавить `"netbind"` в `FACADES`)
- Test: `tests/test_sys_netbind.py`

**Step 1: Тесты**

```python
import socket
import sys

import pytest

from src.sys.linux import netbind as linux_netbind
from src.sys.windows import netbind as win_netbind


@pytest.mark.skipif(sys.platform != "linux", reason="SO_BINDTODEVICE")
def test_linux_bind_to_loopback_without_privileges():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        linux_netbind.bind_to_interface(sock, "lo", socket.AF_INET)
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, 16).rstrip(b"\0") == b"lo"


def test_linux_interface_kind_reads_sysfs(tmp_path, monkeypatch):
    (tmp_path / "wlp1s0" / "wireless").mkdir(parents=True)
    (tmp_path / "enp3s0").mkdir()
    monkeypatch.setattr(linux_netbind, "SYS_CLASS_NET", tmp_path)
    assert linux_netbind.interface_kind("wlp1s0") == "wifi"
    assert linux_netbind.interface_kind("enp3s0") == "ethernet"
    assert linux_netbind.interface_kind("tun0") == "other"


def test_windows_bind_sets_unicast_if_with_index_in_network_order(monkeypatch):
    calls = []

    class Sock:
        family = socket.AF_INET

        def setsockopt(self, level, opt, value):
            calls.append((level, opt, value))

    monkeypatch.setattr(win_netbind, "_adapter_index", lambda alias: 12)
    win_netbind.bind_to_interface(Sock(), "Wi-Fi", socket.AF_INET)
    assert calls == [(socket.IPPROTO_IP, 31, (12).to_bytes(4, "big"))]


def test_windows_interface_kind_from_description(monkeypatch):
    monkeypatch.setattr(win_netbind, "_adapter_description",
                        lambda alias: "Intel(R) Wi-Fi 6 AX201 160MHz")
    assert win_netbind.interface_kind("Wi-Fi") == "wifi"
```

**Step 2: FAIL. Step 3: Реализовать**

- `src/sys/netbind.py` — фасад по образцу `src/sys/resolver.py`, экспортирует `bind_to_interface(sock, interface, family)` и `interface_kind(interface) -> str` («wifi», «ethernet», «other»).
- Linux: `sock.setsockopt(SOL_SOCKET, SO_BINDTODEVICE, interface.encode() + b"\0")`; `SYS_CLASS_NET = Path("/sys/class/net")`.
- Windows: `IP_UNICAST_IF = 31`, `IPV6_UNICAST_IF = 31`; индекс адаптера из `src.sys.windows.netinfo.snapshot().adapter(alias).index`; для IPv4 — `DWORD` в сетевом порядке байт, для IPv6 — в хостовом. Комментарий: «значение не подтверждено на живой Windows, см. открытый вопрос 5 дизайна».
- В `tests/test_sys_facades.py` добавить `"netbind"` в `FACADES`.

**Step 4: PASS** (`tests/test_sys_netbind.py`, `tests/test_sys_facades.py`) → коммит `feat(sys): фасад привязки сокета к интерфейсу`

### Task 3.4: HTTPS-проба напрямую

**Files:**
- Create: `src/diag/probes/https.py`
- Test: `tests/test_diag_probe_https.py`
- Эталон: `probe/HttpsProbe.kt` (149 строк), `probe/ProbeHttpTimings.kt`, `ConnectionProbesTest.kt`

**Тесты на `ScriptedHttpsServer`:** успех с `expectedStatus`/`expectedBody` → `SUCCESS`, evidence `tlsVersion`, `alpn`, `responseMatched=true`, `receivedBytes`, тайминги `tcpMs/tlsMs/headersMs/bodyMs` присутствуют; другое тело → `FAILURE(UNEXPECTED_RESPONSE)`; тело больше `max_bytes` → `FAILURE(BODY_LIMIT)` и чтение остановлено (сервер отдаёт 10 КиБ, проба читает ≤ max+1); 403 → `FAILURE(HTTP_REJECTED)`, `http_status=403`; редирект 302 не следует → `UNEXPECTED_RESPONSE`; неверный сертификат (контекст без CA) → `TLS_CERTIFICATE`; закрытый порт → `CONNECTION_REFUSED`; таймаут (сервер «молчит» — сокет слушает без accept) → `TIMEOUT`; `cancel.set()` до вызова → `CANCELLED(USER_CANCELLED)`; `Host` заголовок равен hostname цели, запрос ушёл на IP из аргумента; `bind` вызывается перед `connect` с интерфейсом из контекста.

**Реализация:** `HttpsProbe(ssl_context_factory=None)` с `run(task, target, address, ctx: ProbeContext) -> ProbeObservation`; сокет `socket.socket(AF_INET)`, `ctx.bind(sock)`, регистрация в `ctx.sockets`, `settimeout`, `connect((ip, port))`, `wrap_socket(server_hostname=hostname)` с `ssl.create_default_context()` (ALPN `h2`, `http/1.1`; при `h2` запрос всё равно по HTTP/1.1 — как `HttpsProbe.kt` через OkHttp не делает; поэтому ALPN предлагать только `http/1.1`, а в evidence писать выбранный), запрос `GET path HTTP/1.1` с `Host`, `User-Agent: Veblock-Diagnostics`, `Connection: close`, чтение заголовков до `\r\n\r\n` (лимит 16 КиБ), тела до `max_bytes + 1`.

Коммит: `feat(diag): HTTPS-проба напрямую с таймингами и лимитом тела`

### Task 3.5: Проба через туннель

**Files:**
- Create: `src/diag/probes/tunnel.py`, `src/diag/session.py`
- Test: `tests/test_diag_probe_tunnel.py`
- Эталон: `data/diagnostics/DiagnosticTunnelSessionSource.kt`, туннельная ветка `HttpsProbe.kt`

**Тесты:** локальный HTTP-прокси в потоке (простой CONNECT-туннель к `ScriptedHttpsServer`, проверяет `Proxy-Authorization`); успех → `SUCCESS`, route `ACTIVE_TUNNEL`; прокси отвечает 407 → `PROXY_AUTH`; порт прокси закрыт → `PROXY_UNAVAILABLE`; `TunnelSessionSource.token()` меняется между «до» и «после» → `CANCELLED(VPN_SESSION_CHANGED)`; `token()` is None → `SKIPPED(PROXY_UNAVAILABLE)`; `requests.Session.trust_env is False`.

**Реализация:** `TunnelSessionSource(context)`: `token()` → `(endpoint.port, endpoint.credentials.user, is_running)` или `None`. `TunnelHttpsProbe(session_source)`: `requests.Session()` с `trust_env=False`, `proxies={"https": endpoint.proxy_url}`, `stream=True`, `allow_redirects=False`, таймаут `(connect, read)` из задачи, чтение `iter_content` до лимита; классификация `requests.exceptions.ProxyError` с 407 → `PROXY_AUTH`.

Коммит: `feat(diag): проба через health-inbound сеанса Veblock`

### Task 3.6: DNS-пробы

**Files:**
- Create: `src/diag/probes/dns.py`
- Test: `tests/test_diag_probe_dns.py`
- Эталон: `probe/SystemDnsProbe.kt`, `DnsTransportProbe.kt`, `DohProbe.kt`, `DiagnosticDohEndpoints.kt`, `BoundDnsTransportExchange.kt`, тесты `DnsProbesTest.kt`, `DohProbeTest.kt`

**Тесты на `FakeDnsServer` и `ScriptedHttpsServer`:**
- system: ответ A → `SUCCESS`, evidence `resolver=system`, `dnsRcode=0`, `dnsMs`; адреса возвращаются вызывающему (поле `addresses` результата); NXDOMAIN → `FAILURE(DNS_FAILED)` с `dnsRcode=3`; UDP с TC → повтор по TCP (в `queries` сервера есть `("udp", …)` и `("tcp", …)`); только TC без TCP-ответа → `DNS_TRUNCATED`; нет серверов → `SKIPPED(DNS_FAILED)`; ответ с частным адресом → `FAILURE(UNSAFE_ADDRESS)`.
- transport: `cloudflare-dns-udp-1` к адресу тестового сервера (адрес инжектируется через `resolvers=`), TXT `id.server` CH → `SUCCESS` при совпадении regex, иначе `UNEXPECTED_RESPONSE`; nxdomain-проба: NXDOMAIN → `SUCCESS`, ответ A → `FAILURE(UNEXPECTED_RESPONSE)`.
- doh: POST `application/dns-message` на локальный HTTPS, тело запроса разбирается `parse_query`; ответ больше 16 КиБ → `BODY_LIMIT`; SNI/`Host` = домен DoH, соединение — на bootstrap-IP (в тесте — 127.0.0.1 с подменой `DOH_ENDPOINTS`).

**Реализация:** `SystemDnsProbe(servers_provider)`, `DnsTransportProbe(resolvers)`, `DohProbe(endpoints, ssl_context_factory)`; общий `exchange_udp/exchange_tcp(ctx, server, port, payload, timeout)`; `DOH_ENDPOINTS = (("cloudflare-doh", "cloudflare-dns.com", "1.1.1.1"), ("google-doh", "dns.google", "8.8.8.8"))`; порты 53/443 параметризуются для тестов. Все сокеты через `ctx.bind` и `ctx.sockets`.

Коммит: `feat(diag): DNS-пробы: системный резолвер, UDP/TCP, DoH`

### Task 3.7: TCP и TLS пробы причин, TELEGRAM_APP

**Files:**
- Create: `src/diag/probes/tcp.py`, `src/diag/probes/tls.py`, `src/diag/probes/telegram.py`
- Test: `tests/test_diag_probe_causes.py`
- Эталон: `probe/TcpProbe.kt`, `TlsProbe.kt`, `TelegramProbe.kt`, `TelegramProbeTest.kt`, часть `ConnectionProbesTest.kt`

**Тесты:** TCP к открытому порту → `SUCCESS` с `tcpMs`; к закрытому → `CONNECTION_REFUSED`; TLS к `ScriptedHttpsServer` с SNI и `CERT_NONE` → `SUCCESS` с `tlsVersion`; сервер, который рвёт соединение после ClientHello (сырой TCP-сервер, читающий и закрывающий) → `CONNECTION_RESET`/`TLS_FAILED` в зависимости от исключения — оба допустимы, зафиксировать как в Kotlin; TELEGRAM_APP: TCP+TLS к адресу DC (в тесте — локальный) → `SUCCESS`, `transport=tcp`.

Коммит: `feat(diag): пробы причин TCP/TLS и проверка Telegram DC`

### Task 3.8: Медиа-пробы

**Files:**
- Create: `src/diag/probes/media.py`
- Test: `tests/test_diag_probe_media.py`, фикстуры `tests/fixtures/diag/telegram_post.html`, `youtube_watch.html` (урезанные фрагменты с нужными тегами, без реальных токенов)
- Эталон: `probe/PublicMediaProbe.kt` (194 строки), `PublicMediaParserTest.kt`, `PublicMediaProbeTest.kt`

**Тесты:** `parse_telegram_og_image(html)` → URL на `cdn4.telesco.pe`, чужой хост → `None`; `parse_youtube_video_url(html)` → URL `*.googlevideo.com`, отсутствие `ytInitialPlayerResponse` → `None`; проба целиком на `ScriptedHttpsServer` (страница + медиа на том же сервере с подменённой проверкой хостов): `SUCCESS` с `mediaStage=media`, `receivedBytes`; страница без ссылки → `FAILURE(UNEXPECTED_RESPONSE)` с `mediaStage=page`, `mediaDetail=no-media-url`; страница больше лимита → `BODY_LIMIT`; `Range: bytes=0-16383` в запросе фрагмента.

**Реализация:** поверх `HttpsProbe` (прямой) или `TunnelHttpsProbe` (туннель) — второй запрос к медиа-хосту с собственным DNS-разрешением через переданный `resolve(hostname)`; лимиты и хосты из дизайна.

Коммит: `feat(diag): медиа-пробы Telegram и YouTube`

### Task 3.9: Сетевой снимок, наблюдатель, kill switch

**Files:**
- Create: `src/diag/network.py`
- Test: `tests/test_diag_network.py`
- Эталон: `data/diagnostics/AndroidDiagnosticNetworkProvider.kt`, `probe/NetworkBaselineProbe.kt`

**Тесты (с подменой `get_default_interface`, `system_dns_servers`, `interface_kind`, `list_network_interfaces`):** `take_snapshot(context)` → `NetworkSnapshot(interface, kind, addresses, dns_servers)`; нет интерфейса → `None`; `NetworkWatcher(loop, take, on_change, interval=3)` зовёт `on_change` при изменении DNS, не зовёт при равенстве, останавливается по `stop()`; `direct_allowed(context)` False при `_holds_full_block()` или `ConnectionState.BLOCKED`; `NetworkBaselineProbe` → наблюдение фазы 0 с evidence `networkType`, `vpnActive`.

Коммит: `feat(diag): снимок сети, слежение за сменой сети и kill switch`

---

## Этап 4. Оценщики и итог

Каждая задача: открыть указанный `.kt` и его тест, перенести дословно. Все оценки — замороженные dataclass'ы в `src/diag/models.py` (поля из Kotlin). Сценарии тестов — из парного `*Test.kt`, не меньше того количества, что там есть.

### Task 4.1: Белые списки

**Files:** Create `src/diag/assess/__init__.py`, `src/diag/assess/allowlist.py`; Test `tests/test_diag_assess_allowlist.py`. Эталон: `DiagnosticAllowlistAssessor.kt` (115 строк), `DiagnosticAllowlistAssessmentTest.kt`, `DiagnosticAllowlistIntegrationTest.kt`.

Ключевые проверки: пороги 3/2/6/3/2; `needs_tie_break`; РФ-ресурсы 3/4 + другие 0/9 → `POSSIBLE`; всё доступно → `NO_PATTERN`; всё недоступно → `NO_ACCESS`; одна попытка без повтора → `MISSING_REPEAT` и `INSUFFICIENT`; `UNVERIFIED_PLACEMENT` при адресе вне реестра; `SHARED_GROUP`.

Коммит: `feat(diag): оценка белых списков`

### Task 4.2: Сервисы

**Files:** Create `src/diag/assess/services.py`; Test `tests/test_diag_assess_services.py`. Эталон: `DiagnosticServiceAssessor.kt`, `DiagnosticServiceAssessorTest.kt`.

Ключевые проверки: `UNAVAILABLE` только при неудаче попыток 1 и 2 или ≥3 отказах резолверов; одна неудача → `PARTIAL`; нет проб → `NOT_CHECKED`; туннель доступен при недоступном прямом → строка «через Veblock доступен».

Коммит: `feat(diag): оценка доступа к сервисам`

### Task 4.3: DNS

**Files:** Create `src/diag/assess/dns.py`; Test `tests/test_diag_assess_dns.py`. Эталон: `DiagnosticDnsAssessor.kt` (144 строки), `DiagnosticDnsAssessorTest.kt`, дизайн `2026-10-29-network-diagnostics-dns-verdict-design.md`.

Ключевые проверки: приоритет вердиктов; SPOOFING при небезопасном адресе; SPOOFING при общей заглушке у разных владельцев, отсутствующей в DoH; разные публичные IP сами по себе не подмена; `WORKING_DOH_BLOCKED`; `UNSTABLE` при расхождении `-dns-system` и `-dns-system-2`; `HIDES_DOMAINS` при NXDOMAIN на известных доменах, когда DoH отвечает.

Коммит: `feat(diag): оценка DNS`

### Task 4.4: Причины

**Files:** Create `src/diag/assess/causes.py`; Test `tests/test_diag_assess_causes.py`. Эталон: `DiagnosticCauseAssessor.kt`, `DiagnosticCauseAssessorTest.kt`.

Ключевые проверки: `TLS_BLOCKED_BY_NAME` (TCP ok, TLS с SNI падает, контроль ok); `CONNECTION_FAILED`; `CERTIFICATE`; `AFTER_HANDSHAKE`; контроль недоступен → `CONTROL_LIMITED`; `top_causes` при равенстве.

Коммит: `feat(diag): оценка причин сбоев`

### Task 4.5: Классификатор и рекомендации

**Files:** Create `src/diag/assess/classifier.py`, `src/diag/assess/recommendations.py`; Test `tests/test_diag_assess_classifier.py`. Эталон: `DiagnosticClassifier.kt` (151 строка), `DiagnosticRecommendations.kt`, `DiagnosticClassifierTest.kt`.

Все коды находок из дизайна, кроме QUIC и captive portal (в enum остаются, тесты фиксируют, что без QUIC-наблюдений находок `QUIC_*` нет). Рекомендации: CHECK_SYSTEM_DNS, OPEN_WIFI_LOGIN, USE_ACTIVE_VPN, TRY_OTHER_PROFILE, REPEAT_STABLE_NETWORK, RETRY_LATER, CHECK_SYSTEM_NETWORK.

Коммит: `feat(diag): классификатор находок и рекомендации`

### Task 4.6: Итог и текст итога

**Files:** Create `src/diag/assess/summary.py`, `src/diag/assess/summary_text.py`; Test `tests/test_diag_summary.py`. Эталон: `DiagnosticSummary.kt`, `DiagnosticSummaryText.kt`, их тесты, дизайн `2026-11-05-network-diagnostics-summary-and-causes-design.md`.

Тест текста — построчное сравнение с образцом из дизайна (заголовок с версией, датой, ОС; строка сети; итог; белые списки; сервисы; DNS; причины; состояние). Дата и ОС передаются параметрами (`now`, `platform_name`), чтобы тест был детерминирован. Строка «Проверка завершена, проб: N» / «Проверка прервана: смена сети» / «Повтор этапа: DNS».

Коммит: `feat(diag): итоговый вердикт и текст итога`

### Task 4.7: Отчёт и сборка оценок

**Files:** Modify `src/diag/models.py` (`DiagnosticReport`), Create `src/diag/assess/report.py` (`assess(context, observations, termination, catalog, registry, previous=None) -> DiagnosticReport`); Test `tests/test_diag_report.py`.

Тесты: пересборка после каждого пакета даёт тот же результат, что одна сборка в конце; при `section=DNS` оценки других этапов берутся из `previous`; `INTERNAL_ERROR` при исключении в оценщике с частичным отчётом.

Коммит: `feat(diag): сборка отчёта из наблюдений`

---

## Этап 5. Runner, экспорт, CLI

### Task 5.1: Runner и use case

**Files:**
- Create: `src/diag/runner.py`
- Test: `tests/test_diag_runner.py`
- Эталон: `NetworkDiagnosticRunner.kt`, `RunNetworkDiagnostics.kt` (169 строк), `AndroidDiagnosticEnvironmentFactory.kt`, `RunNetworkDiagnosticsTest.kt`

**Тесты (все пробы поддельные, `ImmediateLoop`):** события `Started → Observation… → Updated… → Finished`; `cancel()` → `USER_CANCELLED`; смена снимка сети → `NETWORK_CHANGED`; при `COMPLETED` с неудачами use case запускает этап причин с `detail_target_ids` упавших целей (≤ 32) и `deadline_ms=60_000`; при kill switch прямые задачи `SKIPPED(SYSTEM_RESTRICTED)` без вызова проб; ядро не запущено → туннельных задач нет; просроченный каталог → находка `CATALOG_STALE`; повреждённый каталог → `CatalogError` до старта.

**Реализация:** `DiagnosticEnvironment(catalog, registry, snapshot, session_source, probes, direct_allowed)`; `build_environment(context)`; `NetworkDiagnosticRunner(loop)` с `run(request, env, on_event) -> Handle(cancel)`; `RunNetworkDiagnostics(context, loop)` — оркестратор основной проверки и этапа причин; события — замороженные dataclass'ы `Started/Observation/Updated/Finished`.

Коммит: `feat(diag): запуск диагностики и автоматический этап причин`

### Task 5.2: Экспорт схемы 2

**Files:**
- Create: `src/diag/export.py`
- Test: `tests/test_diag_export.py`
- Эталон: `DiagnosticReportRedactor.kt`, `DiagnosticReportExporter.kt`, `DiagnosticReportExporterTest.kt`

**Тесты:** `schemaVersion == 2`; `context.platform in {"linux","windows"}`; в JSON нет ни одной подстроки, похожей на IPv4 (`\d+\.\d+\.\d+\.\d+`), ни URL, ни hostname целей (только токены `t1…`); токены целей общие для `observations` и `causes.observations`; `o1…`/`c1…`; больше 1024 наблюдений → обрезка с пометкой `truncated`; размер ≤ 1 МиБ; `export_filename(report) == f"veblock-diagnostics-{run_id[:8]}.json"`.

Коммит: `feat(diag): экспорт отчёта схемы 2 без личных данных`

### Task 5.3: Команда CLI `diagnose`

**Files:**
- Modify: `cli.py` (новая `cmd_diagnose`, подпарсер после `run`)
- Test: `tests/test_cli_diagnose.py`

**Тесты:** `python cli.py diagnose --help` без ошибки; с подменённым `RunNetworkDiagnostics` (через `monkeypatch`) печатает текст итога и пишет JSON по `--json`; `--section dns` передаёт секцию.

**Реализация:** аргументы `--json ПУТЬ`, `--section {all,allowlist,services,dns}`, `--no-tunnel`; `ImmediateLoop`; прогресс в stderr по одному символу на наблюдение; код выхода 0 при `COMPLETED`, 2 при прерывании.

Коммит: `feat(cli): команда diagnose`

---

## Этап 6. Состояние экрана и представление

### Task 6.1: `DiagnosticsSession`

**Files:**
- Create: `src/ui/logic/diagnostics_session.py`
- Test: `tests/test_ui_diagnostics_session.py`
- Эталон: `NetworkDiagnosticsViewModel.kt` в `app/src/main/java/com/wingeon/app/ui/screen/` (поведение: запуск, остановка, повтор секции, автоматический этап причин, отмена при закрытии)

**Тесты (поддельный `RunNetworkDiagnostics`, `ImmediateLoop`):** `start()` → `running`, `report is None`; `Finished` → `done`; второй `start()` при `running` игнорируется с тостом «Проверка уже идёт»; `retry(section)` сохраняет остальной отчёт; `stop()` → `cancel` и `failed(USER_CANCELLED)`; `close()` отменяет; `changed` колбэк на каждое событие; свойства для кнопок: `can_start`, `can_stop`, `can_export`.

Коммит: `feat(ui): состояние экрана диагностики сети`

### Task 6.2: `DiagnosticsView`

**Files:**
- Create: `src/ui/logic/diagnostics_view.py`
- Test: `tests/test_ui_diagnostics_view.py`
- Эталон: `ui/screen/NetworkDiagnosticsScreen.kt` и `res/values/strings.xml` (все `diagnostics_*` строки)

**Тесты:** `diagnostics_view(session) -> DiagnosticsView(header, summary, cards, details, actions)`; `header.network_line == "Wi-Fi · Veblock подключён (TUN)"`; предупреждение kill switch; карточки в порядке «Белые списки», «Доступ к сервисам», «DNS», «Причины»; чипы «Ожидает»/«Идёт»/«Готово»/«Неполно»; DNS-карточка с тремя фактами; рекомендации → `Action(code, label, kind)`; при `idle` — только кнопка «Проверить сеть»; тексты не содержат «профиль» (`tests/test_branding.py` расширяется проверкой словаря).

Коммит: `feat(ui): представление диагностики сети без тулкита`

---

## Этап 7. Интеграция в приложение

### Task 7.1: Действие, меню, контроллер, Shell

**Files:**
- Modify: `src/ui/logic/menus.py:13-20` (пункт после `test-latency`)
- Modify: `src/ui/controller.py:52-98` (`Shell.show_network_diagnostics(session)`), новый метод `open_network_diagnostics()`
- Modify: `src/ui/application.py:40-50, 245-265` (`_ACCELS["app.network-diagnostics"] = ["<Control>d"]`, обработчик)
- Modify: `src/ui/qt/application.py:195-215`, `src/ui/qt/dialogs/shortcuts.py:17` (`"network-diagnostics": "Ctrl+D"`)
- Modify: `src/ui/shortcuts.py:14-21` (строка «Диагностика сети»)
- Modify: `tests/test_ui_controller.py:40-105` (`FakeShell.show_network_diagnostics`)
- Test: `tests/test_ui_controller.py`, новый `tests/test_ui_menus.py` (проверка `MAIN_MENU`)

**Тесты:**

```python
def test_open_network_diagnostics_hands_session_to_shell(made):
    controller, shell = made
    controller.open_network_diagnostics()
    assert shell.calls[-1][0] == "show_network_diagnostics"
    session = shell.calls[-1][1]
    controller.open_network_diagnostics()
    assert shell.calls[-1][1] is session  # повтор активирует ту же сессию


def test_main_menu_has_network_diagnostics_after_latency():
    names = [name for name, _ in MAIN_MENU]
    assert names.index("network-diagnostics") == names.index("test-latency") + 1
```

Коммит: `feat(ui): действие и пункт меню «Диагностика сети…»`

### Task 7.2: Окно GTK

**Files:**
- Create: `src/ui/dialogs/network_diagnostics.py`
- Modify: `src/ui/application.py:53-160` (`_GtkShell.show_network_diagnostics`), `src/ui/pages/monitoring.py:170-185` (кнопка «Проверить сеть…» рядом с «Обновить сейчас», сигнал `diagnostics-requested`), `src/ui/window.py:193-195` (подключить сигнал к `app.activate_action("network-diagnostics")`)
- Test: `tests/test_ui_network_diagnostics_gtk.py` (маркер `gtk`)

**Тесты:** окно открывается с заголовком «Диагностика сети»; при `idle` видна одна кнопка «Проверить сеть»; после поддельного `Finished` появляются четыре карточки и активны «Скопировать итог»/«Экспорт отчёта…»; закрытие окна зовёт `session.close()`; кнопка на вкладке «Диагностика» активирует действие.

**Реализация:** `NetworkDiagnosticsWindow(Adw.Window)` → `Adw.ToolbarView`, `Gtk.ScrolledWindow`, `Adw.PreferencesGroup` на карточку, `Adw.ActionRow` на строку, `Adw.ExpanderRow` для деталей, `Gtk.ProgressBar`; перерисовка целиком из `diagnostics_view(session)` при `changed`; экспорт — `Gtk.FileDialog().save()` с именем `export_filename`; «Скопировать итог» — `Gdk.Clipboard.set(text)` и тост.

Коммит: `feat(ui): окно «Диагностика сети» в GTK`

### Task 7.3: Окно Qt

**Files:**
- Create: `src/ui/qt/dialogs/network_diagnostics.py`
- Modify: `src/ui/qt/application.py:66-160` (`_QtShell.show_network_diagnostics`), `src/ui/qt/window.py:316-350` (кнопка «Проверить сеть…» в окне «Диагностика — Veblock»)
- Test: `tests/test_ui_qt_network_diagnostics.py` (маркер `qt`, фикстура `qapp`, ожидание из `tests/support/qt.py`)

Тесты зеркальны GTK; реализация — `QDialog` с флагом `Qt.Window`, `QScrollArea`, `QGroupBox`/`QFormLayout`, `QTreeWidget` в деталях, `QProgressBar`, `QFileDialog.getSaveFileName`, `QApplication.clipboard()`.

Коммит: `feat(ui): окно «Диагностика сети» в Qt`

### Task 7.4: Рекомендации с действиями

**Files:**
- Modify: `src/ui/logic/diagnostics_view.py`, `src/ui/controller.py` (метод `run_recommendation(code)`), оба окна
- Test: `tests/test_ui_controller.py`

**Тесты:** `CHECK_SYSTEM_DNS` → `shell.calls` содержит `("open_settings", "dns")`; `USE_ACTIVE_VPN` при остановленном ядре → `connect_selected`, при работающем → тост «Veblock уже подключён»; `TRY_OTHER_PROFILE` → `("activate_window",)`; `REPEAT_STABLE_NETWORK` → `session.start()`.

Коммит: `feat(ui): кнопки рекомендаций диагностики`

### Task 7.5: Документация и финальная проверка

**Files:**
- Modify: `CLAUDE.md` (раздел про `src/diag/`, фасад `netbind`, маркеры тестов)
- Modify: `docs/plans/2026-11-02-shared-ui-design.md` (окно «Диагностика сети», действие, пункт меню, `Ctrl+D`)
- Modify: `docs/plans/2026-11-05-network-diagnostics-desktop-design.md` (статус → «реализовано»)
- Modify: `README.md` (если есть раздел возможностей)

```bash
uv run python cli.py lint-all
uv run pytest -q -p no:cacheprovider --no-cov
make test-gtk
make test-qt
```

Expected: всё зелёное. Коммит: `docs: диагностика сети на десктопе`

---

## Этап 8. Проверка на живой системе (ручная, вне CI)

### Task 8.1: Сценарий виртуалки

**Files:**
- Modify: `tests/vm/guest/…` (новый сценарий `diagnostics_tun`: установить deb, подключить TUN к тестовому серверу внутри виртуалки, запустить `tenga-proxy diagnose --json /tmp/r.json`, проверить, что прямые пробы не `SKIPPED(SYSTEM_RESTRICTED)` и в `nft list table inet veblock` счётчики reject не выросли; сценарий `diagnostics_kill_switch`: с `tun_kill_switch` все прямые пробы `SKIPPED(SYSTEM_RESTRICTED)`)
- Run: `make test-vm ARGS="-- -k diagnostics"`

### Task 8.2: Windows `IP_UNICAST_IF`

На живой Windows (CI `windows.yml` или вручную): тест с маркером `windows` в `tests/test_sys_netbind.py` — привязать UDP-сокет к индексу адаптера Wi-Fi и отправить пакет на loopback-сервер; проверить, что `WSAGetLastError` не 10022. Если значение 31 неверно — поправить константу и снять оговорку в дизайне (открытый вопрос 5). До этого прямые пробы при TUN на Windows остаются `SKIPPED(SYSTEM_RESTRICTED)` с текстом из дизайна.

Коммит: `fix(sys): подтверждена привязка сокета на Windows` (или без изменений, если всё верно).

---

## Критерии приёмки

- Полная проверка без сети завершается `NO_NETWORK` за < 1 с; с сетью и без Veblock — ≤ 120 с, с причинами ≤ 180 с.
- Отчёт JSON проходит `tests/test_diag_export.py` (нет IP, URL, hostname) и читается поддержкой так же, как Android-отчёт схемы 2.
- Текст итога построчно совпадает с форматом дизайна.
- `uv run pytest`, `make test-gtk`, `make test-qt`, `uv run python cli.py lint-all` зелёные; `tests/test_sys_facades.py` знает `netbind`.
- Ни один тест не ходит в публичную сеть (проверить `strace -e connect` или запуск с `unshare -n`: `sudo unshare -n uv run pytest tests/test_diag_*.py -q -p no:cacheprovider --no-cov` проходит).
