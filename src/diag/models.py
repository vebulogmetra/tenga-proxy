"""Модели отчёта диагностики: порт DiagnosticModels.kt, DiagnosticRequest.kt и оценок.

Имена enum и коды совпадают с Android: отчёты с обеих платформ читает одна поддержка.
"""

from __future__ import annotations

import enum
import re
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

SCHEMA_VERSION = 1
ALGORITHM_VERSION = 15

MAX_DEADLINE_MS = 120_000
CAUSES_DEADLINE_MS = 60_000
MAX_ATTEMPTS = 384
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_DETAIL_TARGETS = 32

EVIDENCE_KEYS = frozenset(
    {
        "placementGroup", "coverage", "resolver", "validated", "captivePortal",
        "networkType", "vpnActive", "privateDns", "tlsVersion", "alpn", "responseMatched",
        "catalogStale", "receivedBytes", "sampleCount", "medianMs", "errorRatio", "transport",
        "mediaStage", "mediaDetail", "dnsRcode", "dnsMs", "tcpMs", "tlsMs", "headersMs", "bodyMs",
        "dohOverlap", "sharedAnswer",
    }
)  # fmt: skip

_DETAIL_TARGET = re.compile(r"[a-z0-9-]{1,64}")


class _NamedEnum(enum.Enum):
    """Значение равно имени: так enum попадает в JSON отчёта, как на Android."""

    def __str__(self) -> str:
        return self.name


class ProbeRoute(_NamedEnum):
    DIRECT = "DIRECT"
    ACTIVE_TUNNEL = "ACTIVE_TUNNEL"


class ProbeStage(_NamedEnum):
    NETWORK = "NETWORK"
    DNS = "DNS"
    TCP = "TCP"
    TLS = "TLS"
    HTTP = "HTTP"
    UDP = "UDP"
    QUIC = "QUIC"
    QUALITY = "QUALITY"


class ProbeStatus(_NamedEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    INCONCLUSIVE = "INCONCLUSIVE"


class EvidenceLevel(_NamedEnum):
    OBSERVED = "OBSERVED"
    LIKELY = "LIKELY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DiagnosticFailure(_NamedEnum):
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


class DiagnosticTermination(_NamedEnum):
    COMPLETED = "COMPLETED"
    USER_CANCELLED = "USER_CANCELLED"
    NETWORK_CHANGED = "NETWORK_CHANGED"
    DEADLINE = "DEADLINE"
    BACKGROUND = "BACKGROUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AddressFamily(_NamedEnum):
    IPV4 = "IPV4"
    IPV6 = "IPV6"


class DiagnosticSection(_NamedEnum):
    """Этап для повтора одной карточки; полная проверка — section=None, как на Android."""

    ALLOWLIST = "ALLOWLIST"
    SERVICES = "SERVICES"
    DNS = "DNS"
    DETAILS = "DETAILS"

    @property
    def phases(self) -> frozenset[int]:
        return _SECTION_PHASES[self]


_SECTION_PHASES = {
    DiagnosticSection.ALLOWLIST: frozenset({0, 1, 2, 3}),
    DiagnosticSection.SERVICES: frozenset({0, 4, 5, 6}),
    DiagnosticSection.DNS: frozenset({0, 1, 4, 7}),
    DiagnosticSection.DETAILS: frozenset({0, 1, 4, 8}),
}
FULL_RUN_PHASES = frozenset(range(8))


def _check_evidence(evidence: Mapping[str, str]) -> dict[str, str]:
    for key, value in evidence.items():
        if key not in EVIDENCE_KEYS:
            raise ValueError(f"evidence key {key!r} is not allowed")
        if len(value) > 128 or any(not ch.isprintable() for ch in value):
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
    catalog_version: str
    app_version: str
    schema_version: int = SCHEMA_VERSION
    algorithm_version: int = ALGORITHM_VERSION
    section: DiagnosticSection | None = None

    @staticmethod
    def new_run_id() -> str:
        return str(uuid.uuid4())


@dataclass(frozen=True)
class DiagnosticRequest:
    section: DiagnosticSection | None = None
    detail_target_ids: frozenset[str] = frozenset()
    compare_active_tunnel: bool = True
    deadline_ms: int = MAX_DEADLINE_MS
    max_attempts: int = MAX_ATTEMPTS
    max_payload_bytes: int = MAX_PAYLOAD_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail_target_ids", frozenset(self.detail_target_ids))
        if not 0 < self.deadline_ms <= MAX_DEADLINE_MS:
            raise ValueError("deadline_ms out of range")
        if not 0 < self.max_attempts <= MAX_ATTEMPTS:
            raise ValueError("max_attempts out of range")
        if not 0 < self.max_payload_bytes <= MAX_PAYLOAD_BYTES:
            raise ValueError("max_payload_bytes out of range")
        if len(self.detail_target_ids) > MAX_DETAIL_TARGETS or not all(
            _DETAIL_TARGET.fullmatch(item) for item in self.detail_target_ids
        ):
            raise ValueError("bad detail targets")

    @property
    def phases(self) -> frozenset[int]:
        return FULL_RUN_PHASES if self.section is None else self.section.phases


# Белые списки


class AllowlistVerdict(_NamedEnum):
    POSSIBLE = "POSSIBLE"
    NO_PATTERN = "NO_PATTERN"
    NO_ACCESS = "NO_ACCESS"
    PARTIAL_RESTRICTIONS = "PARTIAL_RESTRICTIONS"
    INSUFFICIENT = "INSUFFICIENT"


class AllowlistReason(_NamedEnum):
    INCOMPLETE_RUN = "INCOMPLETE_RUN"
    NETWORK_CHANGED = "NETWORK_CHANGED"
    CATALOG_STALE = "CATALOG_STALE"
    PORTAL = "PORTAL"
    SYSTEM_RESTRICTED = "SYSTEM_RESTRICTED"
    TOO_FEW_SUCCESSES = "TOO_FEW_SUCCESSES"
    TOO_FEW_SUCCESS_GROUPS = "TOO_FEW_SUCCESS_GROUPS"
    TOO_FEW_FAILURES = "TOO_FEW_FAILURES"
    TOO_FEW_FAILURE_GROUPS = "TOO_FEW_FAILURE_GROUPS"
    NO_MEASUREMENTS = "NO_MEASUREMENTS"


class AllowlistSiteState(_NamedEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NO_HTTP = "NO_HTTP"
    UNVERIFIED_PLACEMENT = "UNVERIFIED_PLACEMENT"
    MISSING_REPEAT = "MISSING_REPEAT"
    INCONSISTENT = "INCONSISTENT"
    RESPONSE_REJECTED = "RESPONSE_REJECTED"
    SHARED_GROUP = "SHARED_GROUP"


@dataclass(frozen=True)
class AllowlistPolicy:
    """Нижние пороги — локальная политика: каталог не может их ослабить."""

    success_targets: int = 3
    success_groups: int = 2
    failed_targets: int = 6
    failed_groups: int = 3
    confirmations: int = 2

    def __post_init__(self) -> None:
        if not (3 <= self.success_targets <= 32 and 2 <= self.success_groups <= 32):
            raise ValueError("success floors out of range")
        if not (6 <= self.failed_targets <= 32 and 3 <= self.failed_groups <= 32):
            raise ValueError("failure floors out of range")
        if not 2 <= self.confirmations <= 3:
            raise ValueError("confirmations out of range")


@dataclass(frozen=True)
class AllowlistSiteResult:
    target_id: str
    hostname: str
    state: AllowlistSiteState
    russian_reference: bool = False


@dataclass(frozen=True)
class AllowlistFamilyResult:
    family: AddressFamily
    success_hosts: int
    success_groups: int
    failed_hosts: int
    failed_groups: int
    sites: tuple[AllowlistSiteResult, ...]
    reasons: tuple[AllowlistReason, ...]


@dataclass(frozen=True)
class AllowlistAssessment:
    verdict: AllowlistVerdict
    families: tuple[AllowlistFamilyResult, ...]
    reasons: tuple[AllowlistReason, ...]
    evidence_ids: tuple[str, ...] = ()
    policy: AllowlistPolicy = AllowlistPolicy()
    checked_sites: int = 0
    total_sites: int = 0
    completed: bool = False
    dns_unavailable: bool = False


# Сервисы


class ServiceCheckStatus(_NamedEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True)
class ServiceCheck:
    target_id: str
    purpose: object  # DiagnosticPurpose: enum живёт в catalog.py, без циклического импорта
    status: ServiceCheckStatus
    failure: DiagnosticFailure | None = None
    http_status: int | None = None
    media_detail: str | None = None
    completed: bool = False


@dataclass(frozen=True)
class ServiceRoute:
    route: ProbeRoute
    checks: tuple[ServiceCheck, ...]


@dataclass(frozen=True)
class ServiceAssessment:
    started: bool
    completed: bool
    checked: int
    total: int
    routes: tuple[ServiceRoute, ...]


# DNS


class DnsVerdict(_NamedEnum):
    SPOOFING = "SPOOFING"
    INTERCEPTION = "INTERCEPTION"
    DOMAINS_HIDDEN = "DOMAINS_HIDDEN"
    SYSTEM_NOT_RESPONDING = "SYSTEM_NOT_RESPONDING"
    UNSTABLE = "UNSTABLE"
    WORKING_DOH_BLOCKED = "WORKING_DOH_BLOCKED"
    WORKING = "WORKING"
    UNKNOWN = "UNKNOWN"


class SystemDnsFact(_NamedEnum):
    ANSWERS = "ANSWERS"
    UNSTABLE = "UNSTABLE"
    HIDES_DOMAINS = "HIDES_DOMAINS"
    SPOOFS = "SPOOFS"
    NOT_RESPONDING = "NOT_RESPONDING"
    UNKNOWN = "UNKNOWN"


class PublicDnsFact(_NamedEnum):
    REACHES = "REACHES"
    INTERCEPTED = "INTERCEPTED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class SecureDnsFact(_NamedEnum):
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class DnsCheckStatus(_NamedEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIAL = "PARTIAL"
    SUSPICIOUS = "SUSPICIOUS"
    UNKNOWN = "UNKNOWN"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True)
class DnsCheck:
    label: str
    resolver: str
    status: DnsCheckStatus
    failure: DiagnosticFailure | None = None
    rcode: str | None = None
    family: AddressFamily | None = None


@dataclass(frozen=True)
class DnsAssessment:
    verdict: DnsVerdict
    started: bool
    completed: bool
    checked: int
    total: int
    checks: tuple[DnsCheck, ...]
    doh_available: bool = False
    system_dns: SystemDnsFact = SystemDnsFact.UNKNOWN
    public_dns: PublicDnsFact = PublicDnsFact.UNKNOWN
    secure_dns: SecureDnsFact = SecureDnsFact.UNKNOWN
    affected_hosts: tuple[str, ...] = ()


# Причины


class FailureCause(_NamedEnum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    TLS_BLOCKED_BY_NAME = "TLS_BLOCKED_BY_NAME"
    TLS_FAILED = "TLS_FAILED"
    CERTIFICATE = "CERTIFICATE"
    AFTER_HANDSHAKE = "AFTER_HANDSHAKE"


@dataclass(frozen=True)
class CauseAssessment:
    causes: Mapping[str, FailureCause] = field(default_factory=dict)
    total: int = 0

    @property
    def top_cause_count(self) -> int:
        return max(Counter(self.causes.values()).values(), default=0)

    @property
    def top_causes(self) -> tuple[FailureCause, ...]:
        """Все причины с наибольшим счётом: выбрать одну при равенстве значило бы исказить итог."""
        counts = Counter(self.causes.values())
        top = self.top_cause_count
        return tuple(cause for cause in FailureCause if counts.get(cause) == top and top)


# Отчёт


@dataclass(frozen=True)
class DiagnosticCoverage:
    successful: int
    failed: int
    unsupported: int
    skipped: int
    cancelled: int
    inconclusive: int


@dataclass(frozen=True)
class DiagnosticNetworkFacts:
    type: str | None
    vpn_active: bool | None


@dataclass(frozen=True)
class DiagnosticReport:
    context: DiagnosticRunContext
    observations: tuple[ProbeObservation, ...] = ()
    findings: tuple[DiagnosticFinding, ...] = ()
    termination: DiagnosticTermination = DiagnosticTermination.COMPLETED
    allowlist_assessment: AllowlistAssessment | None = None
    service_assessment: ServiceAssessment | None = None
    dns_assessment: DnsAssessment | None = None
    cause_assessment: CauseAssessment | None = None

    def __post_init__(self) -> None:
        ids = [item.id for item in self.observations]
        known = set(ids)
        if len(known) != len(ids):
            raise ValueError("observation ids must be unique")
        if not all(oid in known for f in self.findings for oid in f.observation_ids):
            raise ValueError("finding refers to an unknown observation")

    @property
    def is_partial(self) -> bool:
        return self.termination is not DiagnosticTermination.COMPLETED

    @property
    def coverage(self) -> DiagnosticCoverage:
        counts = Counter(item.status for item in self.observations)
        return DiagnosticCoverage(
            counts[ProbeStatus.SUCCESS],
            counts[ProbeStatus.FAILURE],
            counts[ProbeStatus.UNSUPPORTED],
            counts[ProbeStatus.SKIPPED],
            counts[ProbeStatus.CANCELLED],
            counts[ProbeStatus.INCONCLUSIVE],
        )

    def network_facts(self) -> DiagnosticNetworkFacts | None:
        for item in self.observations:
            if (
                item.stage is ProbeStage.NETWORK
                and item.target_id == "network"
                and item.failure_code is None
            ):
                vpn = item.evidence.get("vpnActive")
                return DiagnosticNetworkFacts(
                    item.evidence.get("networkType"),
                    {"true": True, "false": False}.get(vpn or ""),
                )
        return None
