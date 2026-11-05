"""Каталог целей и реестр размещений: порт DiagnosticTarget.kt и двух репозиториев.

Файлы `assets/diagnostics/*.json` — те же, что в Android: один каталог на все платформы.
"""

from __future__ import annotations

import enum
import ipaddress
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from src.core.config import get_asset_path
from src.diag.models import AddressFamily

MAX_CATALOG_BYTES = 128 * 1024
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_FORBIDDEN_SUFFIXES = (".local", ".localhost", ".internal", ".test")

# Проверенные российские ориентиры; это не обещание доступности у конкретного оператора.
RUSSIAN_REFERENCES = frozenset({"yandex.ru", "ya.ru", "vk.com", "ok.ru"})


class CatalogError(ValueError):
    """Файл каталога повреждён: проверку нельзя запускать."""


class DiagnosticPurpose(enum.Enum):
    BASELINE = "BASELINE"
    TELEGRAM_WEB = "TELEGRAM_WEB"
    TELEGRAM_APP = "TELEGRAM_APP"
    INSTAGRAM_WEB = "INSTAGRAM_WEB"
    INSTAGRAM_MEDIA = "INSTAGRAM_MEDIA"
    TELEGRAM_MEDIA = "TELEGRAM_MEDIA"
    YOUTUBE_WEB = "YOUTUBE_WEB"
    YOUTUBE_VIDEO = "YOUTUBE_VIDEO"
    CONTROL = "CONTROL"


@dataclass(frozen=True)
class DiagnosticTarget:
    id: str
    hostname: str
    placement_group: str
    port: int = 443
    path: str = "/"
    purpose: DiagnosticPurpose = DiagnosticPurpose.BASELINE
    max_bytes: int = 65536
    expected_status: int | None = None
    expected_body: str | None = None
    families: tuple[AddressFamily, ...] = (AddressFamily.IPV4, AddressFamily.IPV6)
    coverage: str = "web"


@dataclass(frozen=True)
class DiagnosticCatalog:
    schema_version: int
    catalog_version: int
    expires_at: int
    targets: tuple[DiagnosticTarget, ...]

    def target(self, target_id: str) -> DiagnosticTarget:
        for item in self.targets:
            if item.id == target_id:
                return item
        raise KeyError(target_id)

    def dns_targets(self) -> tuple[DiagnosticTarget, ...]:
        """CDN и цепочка CNAME Instagram только шумят в вердикте DNS."""
        excluded = {DiagnosticPurpose.INSTAGRAM_WEB, DiagnosticPurpose.INSTAGRAM_MEDIA}
        return tuple(item for item in self.targets if item.purpose not in excluded)

    def is_stale(self, now: float | None = None) -> bool:
        return self.expires_at <= (time.time() if now is None else now)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def _parse_target(raw: dict) -> DiagnosticTarget:
    try:
        target = DiagnosticTarget(
            id=raw["id"],
            hostname=raw["hostname"],
            placement_group=raw["placementGroup"],
            port=raw.get("port", 443),
            path=raw.get("path", "/"),
            purpose=DiagnosticPurpose(raw.get("purpose", "BASELINE")),
            max_bytes=raw.get("maxBytes", 65536),
            expected_status=raw.get("expectedStatus"),
            expected_body=raw.get("expectedBody"),
            families=tuple(AddressFamily(f) for f in raw.get("families", ("IPV4", "IPV6"))),
            coverage=raw.get("coverage", "web"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CatalogError(f"bad target: {error}") from error
    _check_target(target)
    return target


def _check_target(target: DiagnosticTarget) -> None:
    host = target.hostname
    _require(
        _IDENTIFIER.fullmatch(target.id) and _IDENTIFIER.fullmatch(target.placement_group),
        "bad identifier",
    )
    _require(len(host) <= 253 and "." in host, "bad hostname")
    _require(all(_HOST_LABEL.fullmatch(label) for label in host.split(".")), "bad hostname label")
    _require(any("a" <= ch <= "z" for ch in host), "hostname must have letters")
    _require(not host.endswith(_FORBIDDEN_SUFFIXES), "local hostname")
    _require(target.port == 443, "port must be 443")
    _require(
        len(target.path) <= 256
        and target.path.startswith("/")
        and not target.path.startswith("//"),
        "bad path",
    )
    parts = urlsplit(f"https://{host}{target.path}")
    _require(parts.hostname == host and not parts.query and not parts.fragment, "bad url")
    _require(1 <= target.max_bytes <= 65536 and bool(target.families), "bad limits")
    _require(
        target.expected_status is None or 200 <= target.expected_status <= 299,
        "bad expected status",
    )
    _require(target.expected_body is None or len(target.expected_body) <= 1024, "bad expected body")
    _require(bool(_IDENTIFIER.fullmatch(target.coverage)), "bad coverage")


def parse_catalog(raw: str) -> DiagnosticCatalog:
    _require(len(raw.encode("utf-8")) <= MAX_CATALOG_BYTES, "catalog too large")
    try:
        document = json.loads(raw)
        catalog = DiagnosticCatalog(
            schema_version=document["schemaVersion"],
            catalog_version=document["catalogVersion"],
            expires_at=document["expiresAtEpochSeconds"],
            targets=tuple(_parse_target(item) for item in document["targets"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise CatalogError(f"bad catalog: {error}") from error
    _require(
        catalog.schema_version == 1 and catalog.catalog_version > 0 and catalog.expires_at > 0,
        "bad catalog header",
    )
    _require(2 <= len(catalog.targets) <= 32, "bad target count")
    _require(len({t.id for t in catalog.targets}) == len(catalog.targets), "duplicate target id")
    _require(len({t.placement_group for t in catalog.targets}) >= 2, "too few placement groups")
    return catalog


def load_catalog(path: Path | str | None = None) -> DiagnosticCatalog:
    """Загрузить каталог и оставить в целях только IPv4.

    В TUN прямой IPv6 закрыт всегда (уровень `ipv6_only`), поэтому десктоп его не проверяет.
    Сужение делается здесь, а не в оценщиках: те считают плановые наблюдения по `families`.
    """
    file = Path(path) if path is not None else Path(get_asset_path("diagnostics/targets.json"))
    try:
        raw = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogError(f"catalog unavailable: {error}") from error
    catalog = parse_catalog(raw)
    return replace(
        catalog,
        targets=tuple(replace(t, families=(AddressFamily.IPV4,)) for t in catalog.targets),
    )


def is_public_address(address: str) -> bool:
    """Порт DiagnosticAddressPolicy.kt: повторно применяется прямо перед соединением."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv4Address):
        a, b, c, _ = ip.packed
        return not (
            a in (0, 10, 127)
            or a >= 224
            or (a == 100 and 64 <= b <= 127)
            or (a == 169 and b == 254)
            or (a == 172 and 16 <= b <= 31)
            or (a == 192 and b == 168)
            or (a == 192 and b == 0 and c in (0, 2))
            or (a == 192 and b == 88 and c == 99)
            or (a == 198 and b in (18, 19))
            or (a == 198 and b == 51 and c == 100)
            or (a == 203 and b == 0 and c == 113)
        )
    raw = ip.packed
    return (
        0x20 <= raw[0] <= 0x3F
        and not (raw[0] == 0x20 and raw[1] == 0x01 and raw[2] < 2)
        and raw[:4] != b"\x20\x01\x0d\xb8"
        and not (raw[0] == 0x20 and raw[1] == 0x02)
        and not (raw[0] == 0x3F and raw[1] == 0xFF and raw[2] < 0x10)
    )


class PlacementRegistry:
    """Проверенная локальная политика, отдельно от меток каталога. Адреса отсюда не выходят."""

    def __init__(self, expires_at: int, entries: list[tuple[DiagnosticTarget, list[str]]]):
        _require(expires_at > 0 and len(entries) <= 32, "bad registry header")
        _require(len({t.id for t, _ in entries}) == len(entries), "duplicate registry target")
        self._expires_at = expires_at
        self._rows: list[tuple[DiagnosticTarget, list]] = []
        for target, prefixes in entries:
            _require(
                target.purpose is DiagnosticPurpose.BASELINE and 1 <= len(prefixes) <= 256,
                "bad registry entry",
            )
            networks = []
            for raw in prefixes:
                network = ipaddress.ip_network(raw, strict=False)
                _require(is_public_address(str(network.network_address)), "private prefix")
                low = 8 if network.version == 4 else 16
                _require(network.prefixlen >= low, "prefix too wide")
                networks.append(network)
            self._rows.append((target, networks))
        for index, (target, networks) in enumerate(self._rows):
            for other, others in self._rows[:index]:
                if target.placement_group != other.placement_group:
                    _require(
                        not any(a.overlaps(b) for a in networks for b in others),
                        "prefixes overlap across groups",
                    )

    @classmethod
    def parse(cls, raw: str) -> PlacementRegistry:
        _require(len(raw.encode("utf-8")) <= MAX_CATALOG_BYTES, "registry too large")
        try:
            document = json.loads(raw)
            _require(document["schemaVersion"] == 1, "bad registry schema")
            entries = [
                (_parse_target(item["target"]), list(item["prefixes"]))
                for item in document["entries"]
            ]
            return cls(document["expiresAtEpochSeconds"], entries)
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
            raise CatalogError(f"bad registry: {error}") from error

    @classmethod
    def load(cls, path: Path | str | None = None) -> PlacementRegistry:
        file = (
            Path(path) if path is not None else Path(get_asset_path("diagnostics/placements.json"))
        )
        try:
            return cls.parse(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            raise CatalogError(f"registry unavailable: {error}") from error

    @classmethod
    def empty(cls) -> PlacementRegistry:
        return cls(2**62, [])

    def group(self, target: DiagnosticTarget, address: str, now: float) -> str | None:
        if now < 0 or now >= self._expires_at or not is_public_address(address):
            return None
        ip = ipaddress.ip_address(address)
        for reviewed, networks in self._rows:
            # Семейства каталог сужает при загрузке: сравнение целиком здесь не подходит.
            same = reviewed.id == target.id and reviewed.hostname == target.hostname
            if same and any(ip in net for net in networks if net.version == ip.version):
                return reviewed.placement_group
        return None

    def groups(self, now: float) -> frozenset[str]:
        if now < 0 or now >= self._expires_at:
            return frozenset()
        return frozenset(target.placement_group for target, _ in self._rows)
