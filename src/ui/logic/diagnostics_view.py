"""Что показывает окно «Диагностика сети»: порт карточек Android без тулкита.

GTK и Qt только рисуют `DiagnosticsView`. Значения сравнимы: окно не перестраивает виджеты,
если представление не изменилось, — иначе прокрутка сбрасывалась бы на каждое наблюдение.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from datetime import datetime

from src import __app_name__ as APP
from src.diag.assess import recommendations as rec
from src.diag.assess.summary import SERVICES, DiagnosticSummary, SummaryVerdict
from src.diag.assess.summary_text import build_summary_text
from src.diag.catalog import DiagnosticPurpose as P
from src.diag.models import (
    AddressFamily,
    AllowlistAssessment,
    AllowlistReason,
    AllowlistSiteState,
    AllowlistVerdict,
    DiagnosticNetworkFacts,
    DiagnosticReport,
    DiagnosticSection,
    DiagnosticTermination,
    DnsAssessment,
    DnsCheck,
    DnsCheckStatus,
    DnsVerdict,
    EvidenceLevel,
    FailureCause,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
    PublicDnsFact,
    SecureDnsFact,
    ServiceAssessment,
    ServiceCheck,
    ServiceCheckStatus,
    SystemDnsFact,
)
from src.diag.models import (
    DiagnosticFailure as F,
)
from src.ui.logic.diagnostics_session import DiagnosticsSession

TITLE = "Диагностика сети"
IDLE_TITLE = "Проверка подключения"
IDLE_BODY = (
    "Проверим DNS, доступ к Telegram, Instagram и YouTube. "
    "Покажем, где возникла проблема и что можно сделать."
)
CONSENT = (
    "До 3 мин · до 8 МиБ полезных данных + служебный трафик. Запросы идут напрямую, в том числе "
    f"при подключённом {APP}. Настройки не меняются."
)
RUNNING_TITLE = "Проверяем сеть"
COPY = "Скопировать итог"
COPIED = "Итог скопирован"
EXPORT = "Экспорт отчёта…"
EXPORTED = "Отчёт сохранён"
EXPORT_FAILED = "Не удалось сохранить отчёт. Повторите попытку."
ALREADY_RUNNING = "Проверка уже идёт"
STOP = "Остановить"
START = "Проверить сеть"
START_ALL = "Проверить всю сеть"
RETRY = "Проверить снова"
PREVIOUS = "Предыдущая проверка"
SUMMARY_TITLE = "Итог"
CAUSES_RUNNING = "Определяем причины…"

_ALLOWLIST_TITLE = "Белые списки"
_SERVICES_TITLE = "Доступ к сервисам"
_DNS_TITLE = "DNS"
_TECHNICAL_TITLE = "Технические результаты"
_UNKNOWN = "Не удалось определить"
_SYSTEM_RESTRICTED = (
    "Прямые запросы закрыты в этой системе: блокировка трафика или обход туннеля недоступен."
)
_NETWORK_CHANGED = "Сеть изменилась. Результаты неполные — повторите проверку."
_NO_TUNNEL = f"{APP} не подключён: сравнение через туннель пропущено."
_TUNNEL_CHANGED = f"Подключение {APP} изменилось; сравнение через него остановлено."
_PROXY_AUTH = f"Локальный прокси {APP} отклонил авторизацию."
_TIMEOUT = "Ресурс не ответил вовремя"
_CERTIFICATE = "Сертификат TLS не прошёл проверку."
_BUDGET = "Проверка не завершена: достигнут лимит времени или трафика"
_DNS_UNSAFE = "Получен непубличный или неподходящий адрес; соединение не выполнялось"
_NO_NETWORK = "Не найдена активная физическая сеть с доступом в интернет."
_AMBIGUOUS = "Не удалось выбрать физическую сеть. Повторите проверку."
_NO_CONTROL = "Нужен настроенный контрольный узел. Эта проверка не выполнялась."
_QUIC_FALLBACK = (
    "HTTP/3 не подтверждён: ответ пришёл по TCP либо отсутствует достоверная телеметрия протокола."
)
_DNS_TRUNCATED = "DNS-ответ усечён (TC). Результат TCP проверяется отдельно."


class Tone(enum.Enum):
    GOOD = "good"
    BAD = "bad"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Chip:
    text: str
    tone: Tone = Tone.NEUTRAL


@dataclass(frozen=True)
class Row:
    title: str
    subtitle: str = ""
    tone: Tone = Tone.NEUTRAL
    value: str = ""


@dataclass(frozen=True)
class Group:
    title: str
    summary: str = ""
    rows: tuple[Row, ...] = ()
    expanded: bool = False


@dataclass(frozen=True)
class Card:
    title: str
    section: DiagnosticSection | None = None
    chip: Chip | None = None
    previous: bool = False
    lines: tuple[str, ...] = ()
    progress: float | None = None
    groups: tuple[Group, ...] = ()
    notes: tuple[str, ...] = ()
    retry_enabled: bool = False


@dataclass(frozen=True)
class Action:
    code: str
    label: str
    primary: bool = False


@dataclass(frozen=True)
class DiagnosticsView:
    primary_label: str
    running: bool
    idle: bool = False
    network: str | None = None
    chips: tuple[Chip, ...] = ()
    scope: str | None = None
    warning: str | None = None
    progress_text: str | None = None
    verdict: str | None = None
    verdict_notes: tuple[str, ...] = ()
    state_rows: tuple[tuple[str, Chip], ...] = ()
    causes_running: bool = False
    causes_text: str | None = None
    actions: tuple[Action, ...] = ()
    can_copy: bool = False
    can_export: bool = False
    error: str | None = None
    cards: tuple[Card, ...] = ()
    technical: Card | None = None
    footnotes: tuple[str, ...] = ()
    methodology: tuple[Row, ...] = ()


# Подписи


def recommendation_text(code: str) -> str:
    return {
        rec.CHECK_SYSTEM_DNS: "Настройки DNS",
        rec.USE_ACTIVE_VPN: f"Подключить {APP}",
        rec.TRY_OTHER_PROFILE: "Выбрать другой сервер",
        rec.CHECK_SYSTEM_NETWORK: "Проверьте подключение к сети",
        rec.OPEN_WIFI_LOGIN: "Проверьте подключение к сети",
    }.get(code, "Повторить проверку")


_CAUSES = {
    FailureCause.CONNECTION_FAILED: "соединение не устанавливается",
    FailureCause.TLS_BLOCKED_BY_NAME: (
        "соединение обрывается при TLS, это характерно для фильтрации по имени сайта"
    ),
    FailureCause.TLS_FAILED: "соединение обрывается при TLS",
    FailureCause.CERTIFICATE: "сертификат не прошёл проверку",
    FailureCause.AFTER_HANDSHAKE: "сбой после установки соединения",
}
_SECTIONS = {
    DiagnosticSection.ALLOWLIST: _ALLOWLIST_TITLE,
    DiagnosticSection.SERVICES: _SERVICES_TITLE,
    DiagnosticSection.DNS: _DNS_TITLE,
    DiagnosticSection.DETAILS: _TECHNICAL_TITLE,
}
_ALLOWLIST_LABELS = {
    AllowlistVerdict.POSSIBLE: "Включены",
    AllowlistVerdict.NO_PATTERN: "Не используются",
    AllowlistVerdict.NO_ACCESS: "Нет доступа к сети",
    AllowlistVerdict.PARTIAL_RESTRICTIONS: "Частичные ограничения",
    AllowlistVerdict.INSUFFICIENT: _UNKNOWN,
}
_ALLOWLIST_BODIES = {
    AllowlistVerdict.POSSIBLE: (
        "Часть независимых направлений доступна, другие повторно недоступны. "
        "Вывод относится к проверенной сети и ресурсам."
    ),
    AllowlistVerdict.NO_PATTERN: (
        "Все проверочные сайты в указанном семействе IP ответили в обеих проверках. "
        "Это не гарантирует доступность всех сайтов и приложений."
    ),
    AllowlistVerdict.INSUFFICIENT: (
        "Ниже показано, какие результаты удалось подтвердить. "
        "Малое число отказов само по себе не означает, что ограничений нет."
    ),
}
_SITE_TEXTS = {
    AllowlistSiteState.AVAILABLE: "доступен в двух проверках",
    AllowlistSiteState.UNAVAILABLE: "сетевой отказ в двух проверках",
    AllowlistSiteState.NO_HTTP: "HTTPS-результат не получен; в расчёт не включён",
    AllowlistSiteState.UNVERIFIED_PLACEMENT: (
        "размещение сервера не подтверждено; в расчёт не включён"
    ),
    AllowlistSiteState.MISSING_REPEAT: "не хватает повторной проверки",
    AllowlistSiteState.INCONSISTENT: "результаты неоднозначны или расходятся; в расчёт не включён",
    AllowlistSiteState.RESPONSE_REJECTED: (
        "ответ, сертификат или проверка содержимого не подходят для вывода о блокировке"
    ),
    AllowlistSiteState.SHARED_GROUP: (
        "есть отказ, но другая цель той же группы доступна; в независимые отказы не включён"
    ),
}
_ALLOWLIST_REASONS = {
    AllowlistReason.INCOMPLETE_RUN: "Проверка не завершена: итог по белым спискам недостоверен.",
    AllowlistReason.NETWORK_CHANGED: (
        "Сеть изменилась во время проверки: результаты нельзя объединить."
    ),
    AllowlistReason.CATALOG_STALE: "Каталог проверочных целей устарел или не совпадает с версией отчёта.",
    AllowlistReason.PORTAL: "Сеть сообщает о странице входа Wi-Fi. Сначала пройдите авторизацию.",
    AllowlistReason.SYSTEM_RESTRICTED: (
        "Прямые запросы закрыты; доступность ресурсов нельзя оценить надёжно."
    ),
    AllowlistReason.NO_MEASUREMENTS: "Нет результатов HTTPS для проверочных сайтов.",
    AllowlistReason.TOO_FEW_SUCCESSES: "Не хватает сайтов с повторным успешным ответом.",
    AllowlistReason.TOO_FEW_SUCCESS_GROUPS: (
        "Успешные ответы не покрывают достаточно независимых групп."
    ),
    AllowlistReason.TOO_FEW_FAILURES: "Не хватает сайтов с повторным сетевым отказом.",
    AllowlistReason.TOO_FEW_FAILURE_GROUPS: (
        "Сетевые отказы не покрывают достаточно отдельных независимых групп."
    ),
}
_DNS_ERROR_VERDICTS = (
    DnsVerdict.SPOOFING,
    DnsVerdict.INTERCEPTION,
    DnsVerdict.DOMAINS_HIDDEN,
    DnsVerdict.SYSTEM_NOT_RESPONDING,
)


def cause_text(cause: FailureCause) -> str:
    return _CAUSES[cause]


def dns_verdict_label(verdict: DnsVerdict, hidden: int) -> str:
    return {
        DnsVerdict.SPOOFING: "Обнаружена подмена DNS",
        DnsVerdict.INTERCEPTION: "Обнаружен перехват DNS-запросов",
        DnsVerdict.DOMAINS_HIDDEN: f"DNS-блокировка: скрыто доменов — {hidden}",
        DnsVerdict.SYSTEM_NOT_RESPONDING: "DNS сети не отвечает",
        DnsVerdict.UNSTABLE: "DNS сети отвечает с перебоями",
        DnsVerdict.WORKING_DOH_BLOCKED: "DNS работает, защищённый DNS заблокирован",
        DnsVerdict.WORKING: "DNS работает без вмешательства",
        DnsVerdict.UNKNOWN: "Не удалось проверить",
    }[verdict]


def summary_verdict_label(summary: DiagnosticSummary, hidden: int) -> str:
    verdict = summary.verdict
    if verdict is SummaryVerdict.SOME_SERVICES_BLOCKED:
        return f"Напрямую недоступны: {', '.join(summary.blocked_services)}"
    if verdict is SummaryVerdict.DNS_PROBLEM:
        return dns_verdict_label(summary.dns_verdict or DnsVerdict.UNKNOWN, hidden)
    return {
        SummaryVerdict.MIXED_NETWORKS: "Этапы проверены в разных сетях",
        SummaryVerdict.NO_ACCESS: "Нет доступа к сети",
        SummaryVerdict.ALLOWLIST: "Похоже, оператор включил белые списки",
        SummaryVerdict.PARTIAL_RESOURCES: "Часть ресурсов недоступна напрямую",
        SummaryVerdict.SERVICES_BLOCKED: "Сервисы недоступны напрямую",
        SummaryVerdict.ALL_AVAILABLE: "Проверенные ресурсы доступны",
        SummaryVerdict.UNKNOWN: _UNKNOWN,
    }[verdict]


def network_type_text(kind: str | None) -> str:
    return {"WIFI": "Wi-Fi", "ETHERNET": "Ethernet"}.get(kind or "", "Другая сеть")


def _vpn_text(active: bool) -> str:
    return f"{APP} подключён" if active else f"{APP} отключён"


def _allowlist_chip(assessment: AllowlistAssessment) -> Chip:
    verdict = assessment.verdict
    if verdict is AllowlistVerdict.NO_PATTERN:
        tone = Tone.GOOD
    elif verdict is AllowlistVerdict.INSUFFICIENT:
        tone = Tone.NEUTRAL
    else:
        tone = Tone.BAD
    return Chip(_ALLOWLIST_LABELS[verdict], tone)


def _direct_checks(assessment: ServiceAssessment) -> tuple[ServiceCheck, ...]:
    for route in assessment.routes:
        if route.route is ProbeRoute.DIRECT:
            return route.checks
    return ()


def _service_chip(assessment: ServiceAssessment) -> Chip | None:
    """Пока этап не завершён, чипа нет: счёт незавершённых проверок читался бы как результат."""
    if not assessment.completed:
        return None
    checks = _direct_checks(assessment)
    available = sum(c.status is ServiceCheckStatus.AVAILABLE for c in checks)
    if any(c.status is ServiceCheckStatus.UNAVAILABLE for c in checks):
        tone = Tone.BAD
    elif checks and available == len(checks):
        tone = Tone.GOOD
    else:
        tone = Tone.NEUTRAL
    return Chip(f"{available} из {len(checks)}", tone)


def _dns_chip(assessment: DnsAssessment) -> Chip:
    if assessment.verdict in _DNS_ERROR_VERDICTS:
        tone = Tone.BAD
    elif assessment.verdict is DnsVerdict.WORKING:
        tone = Tone.GOOD
    else:
        tone = Tone.NEUTRAL
    return Chip(dns_verdict_label(assessment.verdict, len(assessment.affected_hosts)), tone)


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _fraction(done: int, total: int) -> float:
    return done / total if total else 0.0


# Карточки


def _allowlist_card(session: DiagnosticsSession, assessment, running, causes) -> Card:
    section = DiagnosticSection.ALLOWLIST
    checking = running and not assessment.completed
    lines: list[str] = []
    progress = None
    if checking:
        lines.append("Собираем данные. Вывод появится после завершения проверки.")
        lines.append(f"Проверено {assessment.checked_sites} из {assessment.total_sites}")
        progress = _fraction(assessment.checked_sites, assessment.total_sites)
    else:
        body = _ALLOWLIST_BODIES.get(assessment.verdict)
        if body:
            lines.append(body)
        if assessment.dns_unavailable:
            lines.append(
                "DNS не разрешил контрольные имена ни одним из проверенных способов. "
                "Определить белый список по этим результатам нельзя."
            )
        lines += [_ALLOWLIST_REASONS[r] for r in assessment.reasons]
        if assessment.verdict is AllowlistVerdict.INSUFFICIENT:
            for family in assessment.families:
                lines += [_ALLOWLIST_REASONS[r] for r in family.reasons]
            lines.append("Повторите проверку при стабильном подключении.")
    groups = []
    for family in assessment.families:
        for russian, title, summary in (
            (True, "Российские ориентиры", "Ресурсы РФ: доступность зависит от оператора."),
            (False, "Другие контрольные направления", ""),
        ):
            sites = [s for s in family.sites if s.russian_reference is russian]
            if sites:
                rows = tuple(_site_row(site, causes) for site in sites)
                groups.append(Group(f"{title} · {family.family.name}", summary, rows))
    return Card(
        _ALLOWLIST_TITLE,
        section,
        None if checking else _allowlist_chip(assessment),
        session.is_previous(section),
        tuple(dict.fromkeys(lines)),
        progress,
        tuple(groups),
        retry_enabled=not session.running,
    )


def _site_row(site, causes) -> Row:
    available = site.state is AllowlistSiteState.AVAILABLE
    unavailable = site.state in (AllowlistSiteState.UNAVAILABLE, AllowlistSiteState.SHARED_GROUP)
    parts = [_SITE_TEXTS[site.state]]
    cause = causes.get(site.target_id)
    if cause is not None and not available:
        parts.append(_capitalized(cause_text(cause)))
    tone = Tone.GOOD if available else Tone.BAD if unavailable else Tone.NEUTRAL
    return Row(site.hostname, " · ".join(parts), tone)


def _service_card(session: DiagnosticsSession, assessment, running, causes) -> Card:
    section = DiagnosticSection.SERVICES
    checking = running and assessment.started and not assessment.completed
    lines: list[str] = []
    progress = None
    if assessment.completed:
        checks = _direct_checks(assessment)
        available = sum(c.status is ServiceCheckStatus.AVAILABLE for c in checks)
        lines.append(f"Доступно функций напрямую: {available} из {len(checks)}")
    if running and not assessment.started:
        lines.append("Начнётся после проверки белых списков")
    if checking:
        lines.append(f"Проверено {assessment.checked} из {assessment.total}")
        progress = _fraction(assessment.checked, assessment.total)
    groups = []
    for route in assessment.routes:
        tunnel = route.route is ProbeRoute.ACTIVE_TUNNEL
        if tunnel and route.checks and all(c.failure is F.PROXY_UNAVAILABLE for c in route.checks):
            lines.append(_NO_TUNNEL)
            continue
        if tunnel:
            title = f"Через {APP}"
            summary = (
                "Сравнение с прямым соединением выполняется"
                if checking
                else "Результаты сравнения с прямым соединением"
            )
        else:
            title = "Напрямую"
            summary = "Доступность веб-страниц и медиа"
        for name, purposes in SERVICES:
            checks = [c for c in route.checks if c.purpose in purposes]
            if checks:
                route_causes = {} if tunnel else causes
                rows = tuple(_service_row(c, checking, route_causes) for c in checks)
                groups.append(Group(f"{title} · {name}", summary, rows))
    return Card(
        _SERVICES_TITLE,
        section,
        _service_chip(assessment),
        session.is_previous(section),
        tuple(lines),
        progress,
        tuple(groups),
        (
            "Публичные страницы и фрагменты медиа без входа в аккаунт. "
            "Доступность остальных функций не гарантируется.",
        ),
        not session.running,
    )


_RESTATED_BY_CAUSE = (
    _TIMEOUT,
    "Соединение сброшено",
    "Не удалось установить соединение",
    "Не удалось установить защищённое соединение",
    _CERTIFICATE,
)


def _service_reason(check: ServiceCheck) -> str:
    if check.media_detail == "media-url-unavailable":
        return "Сервис не выдал доступную прямую ссылку на медиа. Загрузку проверить не удалось."
    if check.media_detail == "media-format-unexpected":
        return "Ответ получен, но ожидаемый формат медиа не распознан."
    if check.http_status is not None and check.http_status >= 300:
        return f"Сервер вернул HTTP {check.http_status}. Это не подтверждает сетевую блокировку."
    return {
        F.TIMEOUT: _TIMEOUT,
        F.UNSAFE_ADDRESS: _DNS_UNSAFE,
        F.DNS_FAILED: "Не удалось получить IP-адрес ресурса",
        F.CONNECTION_RESET: "Соединение сброшено",
        F.CONNECTION_REFUSED: "Не удалось установить соединение",
        F.TLS_FAILED: "Не удалось установить защищённое соединение",
        F.TLS_CERTIFICATE: _CERTIFICATE,
        F.NETWORK_CHANGED: _NETWORK_CHANGED,
        F.VPN_SESSION_CHANGED: _TUNNEL_CHANGED,
        F.SYSTEM_RESTRICTED: _SYSTEM_RESTRICTED,
        F.BUDGET: _BUDGET,
        F.DEADLINE: _BUDGET,
        F.PROXY_UNAVAILABLE: _NO_TUNNEL,
        F.PROXY_AUTH: _PROXY_AUTH,
        F.BODY_LIMIT: "Ответ превышает допустимый размер проверки",
    }.get(check.failure, "Ожидаемый ответ не получен; доступность определить не удалось.")


def _service_row(check: ServiceCheck, checking: bool, causes) -> Row:
    label = {
        P.TELEGRAM_MEDIA: "Публичное изображение",
        P.INSTAGRAM_MEDIA: "Публичное изображение",
        P.YOUTUBE_VIDEO: "Фрагмент видео",
    }.get(check.purpose, "Веб-версия")
    if check.status is ServiceCheckStatus.UNKNOWN:
        status = "Проверяется" if checking and not check.completed else "Не удалось проверить"
    else:
        status = {
            ServiceCheckStatus.AVAILABLE: "Доступен",
            ServiceCheckStatus.UNAVAILABLE: "Недоступен",
            ServiceCheckStatus.PARTIAL: "Частично доступен",
            ServiceCheckStatus.NOT_CHECKED: "Не проверен",
        }[check.status]
    parts = []
    cause = causes.get(check.target_id)
    if check.status not in (ServiceCheckStatus.AVAILABLE, ServiceCheckStatus.NOT_CHECKED):
        reason = _service_reason(check)
        # Причина повторяет эти отказы; HTTP и медиа она не объясняет, как и сбой после рукопожатия.
        restated = (
            cause is not None
            and cause is not FailureCause.AFTER_HANDSHAKE
            and reason in _RESTATED_BY_CAUSE
        )
        if not restated:
            parts.append(reason)
    if cause is not None and check.status is not ServiceCheckStatus.AVAILABLE:
        parts.append(_capitalized(cause_text(cause)))
    if check.status is ServiceCheckStatus.AVAILABLE:
        tone = Tone.GOOD
    elif check.status is ServiceCheckStatus.UNAVAILABLE:
        tone = Tone.BAD
    else:
        tone = Tone.NEUTRAL
    return Row(label, " · ".join(parts), tone, status)


def _dns_reason(check: DnsCheck) -> str:
    failure = check.failure
    if check.status is DnsCheckStatus.AVAILABLE:
        return "Ответ получен"
    if check.status is DnsCheckStatus.SUSPICIOUS and failure is F.UNEXPECTED_RESPONSE:
        return "Ответил не тот сервер, которому отправлен запрос"
    if check.status is DnsCheckStatus.NOT_CHECKED:
        return "Не проверен"
    if check.status is DnsCheckStatus.PARTIAL:
        return "Результаты запросов различаются: часть успешна"
    if failure is F.NETWORK_CHANGED:
        return _NETWORK_CHANGED
    if failure is F.UNSAFE_ADDRESS:
        return _DNS_UNSAFE
    if check.rcode == "3":
        return "DNS сообщил, что домен не существует (NXDOMAIN)"
    if check.rcode == "2":
        return "DNS не смог обработать запрос (SERVFAIL)"
    if failure is F.TIMEOUT:
        return _TIMEOUT
    if failure is F.DNS_TRUNCATED:
        return _DNS_TRUNCATED
    if failure in (F.CONNECTION_REFUSED, F.CONNECTION_RESET, F.IO):
        return "Не удалось получить ответ от DNS"
    if failure is F.DNS_FAILED and check.rcode == "0":
        return "Запись этого типа не получена; это не доказывает блокировку"
    if failure is F.SYSTEM_RESTRICTED:
        return _SYSTEM_RESTRICTED
    if failure in (F.BUDGET, F.DEADLINE):
        return _BUDGET
    if failure is F.USER_CANCELLED:
        return "Отменено"
    if failure is F.HTTP_REJECTED:
        return "Сервер DoH отклонил HTTP-запрос"
    return "Не удалось проверить"


def _visible_dns_checks(checks: list[DnsCheck]) -> list[DnsCheck]:
    """Строка AAAA ничего не добавляет, когда A той же цели ответил: нет записи — не отказ."""
    answered = {
        (c.label, c.resolver)
        for c in checks
        if c.family is AddressFamily.IPV4 and c.status is DnsCheckStatus.AVAILABLE
    }
    return [
        c
        for c in checks
        if c.family is not AddressFamily.IPV6 or (c.label, c.resolver) not in answered
    ]


def _common_failure(checks: list[DnsCheck]) -> str | None:
    if not checks or len({c.status for c in checks}) != 1 or len({c.failure for c in checks}) != 1:
        return None
    return _dns_reason(checks[0]) if checks[0].failure is not None else None


def _dns_row(check: DnsCheck) -> Row:
    suffix = {AddressFamily.IPV4: " · A (IPv4)", AddressFamily.IPV6: " · AAAA (IPv6)"}.get(
        check.family, ""
    )
    if check.status is DnsCheckStatus.AVAILABLE:
        tone = Tone.GOOD
    elif check.status is DnsCheckStatus.UNAVAILABLE:
        tone = Tone.BAD
    else:
        tone = Tone.NEUTRAL
    return Row(check.label + suffix, _dns_reason(check), tone)


def _dns_group(title: str, checks: list[DnsCheck]) -> Group | None:
    if not checks:
        return None
    # Считается только A, как в выводе: AAAA лишь поясняет отказ A.
    counted = [c for c in checks if c.family is not AddressFamily.IPV6]
    available = sum(c.status is DnsCheckStatus.AVAILABLE for c in counted)
    parts = [f"Успешно: {available} из {len(counted)}"]
    common = _common_failure(counted)
    if common:
        parts.append(common)
    rows = tuple(_dns_row(c) for c in _visible_dns_checks(checks))
    return Group(title, " · ".join(parts), rows)


def _dns_lines(assessment: DnsAssessment) -> list[str]:
    verdict = assessment.verdict
    hosts = ", ".join(assessment.affected_hosts)
    body = {
        DnsVerdict.SPOOFING: f"Сеть возвращает ложный адрес для: {hosts}",
        DnsVerdict.INTERCEPTION: (
            "На запросы к публичным DNS-серверам отвечает не тот сервер, которому они отправлены."
        ),
        DnsVerdict.DOMAINS_HIDDEN: (
            f"DNS сети сообщает, что домены не существуют, хотя защищённый DNS их находит: {hosts}"
        ),
        DnsVerdict.WORKING_DOH_BLOCKED: (
            f"Сеть не пропускает DoH к Cloudflare и Google. На работу {APP} это не влияет."
        ),
        DnsVerdict.WORKING: (
            "DNS разрешает проверенные IPv4-имена. "
            "Его смена, вероятно, не устранит ограничения соединений."
        ),
        DnsVerdict.UNKNOWN: (
            "Не удалось отделить проблему DNS от недоступности сети. Повторите проверку."
        ),
    }.get(verdict)
    lines = [body] if body else []
    if verdict in (DnsVerdict.SPOOFING, DnsVerdict.INTERCEPTION, DnsVerdict.DOMAINS_HIDDEN):
        lines.append(f"Через {APP} запросы сайтов идут в туннеле, подмена на них не влияет.")
    if verdict in (
        DnsVerdict.SPOOFING,
        DnsVerdict.DOMAINS_HIDDEN,
        DnsVerdict.SYSTEM_NOT_RESPONDING,
    ):
        lines.append(
            "Адрес сервера определяется через DNS сети: если подключение не устанавливается, "
            "используйте сервер с IP-адресом."
        )
    if (
        verdict
        in (
            DnsVerdict.SPOOFING,
            DnsVerdict.DOMAINS_HIDDEN,
            DnsVerdict.SYSTEM_NOT_RESPONDING,
            DnsVerdict.UNSTABLE,
        )
        and assessment.secure_dns is SecureDnsFact.AVAILABLE
    ):
        lines.append("DNS сети даёт ошибки; защищённый DNS доступен. Его включение может помочь.")
    return lines


_SYSTEM_FACTS = {
    SystemDnsFact.ANSWERS: ("отвечает", Tone.GOOD),
    SystemDnsFact.UNSTABLE: ("отвечает с перебоями", Tone.NEUTRAL),
    SystemDnsFact.HIDES_DOMAINS: ("скрывает домены", Tone.BAD),
    SystemDnsFact.SPOOFS: ("подменяет адреса", Tone.BAD),
    SystemDnsFact.NOT_RESPONDING: ("не отвечает", Tone.BAD),
    SystemDnsFact.UNKNOWN: ("не определено", Tone.NEUTRAL),
}
_PUBLIC_FACTS = {
    PublicDnsFact.REACHES: ("запросы доходят", Tone.GOOD),
    PublicDnsFact.INTERCEPTED: ("перехватываются", Tone.BAD),
    PublicDnsFact.BLOCKED: ("порт 53 закрыт", Tone.NEUTRAL),
    PublicDnsFact.UNKNOWN: ("не определено", Tone.NEUTRAL),
}
_SECURE_FACTS = {
    SecureDnsFact.AVAILABLE: ("доступен", Tone.GOOD),
    SecureDnsFact.BLOCKED: ("заблокирован", Tone.NEUTRAL),
    SecureDnsFact.UNKNOWN: ("не определено", Tone.NEUTRAL),
}


def _dns_facts(assessment: DnsAssessment) -> Group:
    rows = []
    for title, (value, tone) in (
        ("DNS сети", _SYSTEM_FACTS[assessment.system_dns]),
        ("Публичный DNS", _PUBLIC_FACTS[assessment.public_dns]),
        ("Защищённый DNS", _SECURE_FACTS[assessment.secure_dns]),
    ):
        rows.append(Row(title, "", tone, value))
    return Group("", "", tuple(rows), expanded=True)


def _dns_card(session: DiagnosticsSession, assessment: DnsAssessment, running: bool) -> Card:
    section = DiagnosticSection.DNS
    checking = running and assessment.started and not assessment.completed
    lines: list[str] = []
    progress = None
    groups: list[Group | None] = []
    if running and not assessment.started:
        lines.append("После проверки сервисов")
    elif checking:
        lines.append("Проверяется")
        lines.append(f"Проверено {assessment.checked} из {assessment.total}")
        progress = _fraction(assessment.checked, assessment.total)
    else:
        lines += _dns_lines(assessment)
        if assessment.verdict is not DnsVerdict.UNKNOWN:
            groups.append(_dns_facts(assessment))

    def checks(*resolvers: str) -> list[DnsCheck]:
        return [c for c in assessment.checks if c.resolver in resolvers]

    groups += [
        _dns_group("DNS текущей сети", checks("system")),
        _dns_group("Публичный DNS — UDP", checks("udp")),
        _dns_group("Публичный DNS — TCP", checks("tcp")),
        _dns_group("Публичный DNS — проверка перехвата", checks("identity", "nxdomain")),
        _dns_group("Защищённый DNS — Cloudflare", checks("cloudflare-doh")),
        _dns_group("Защищённый DNS — Google", checks("google-doh")),
    ]
    return Card(
        _DNS_TITLE,
        section,
        None if running and not assessment.completed else _dns_chip(assessment),
        session.is_previous(section),
        tuple(lines),
        progress,
        tuple(g for g in groups if g is not None),
        (
            "Напрямую через основную сеть. Разные IP-адреса и отсутствие IPv6-записи "
            "сами по себе не означают блокировку.",
        ),
        not session.running,
    )


# Технические результаты


_FINDINGS = {
    "CATALOG_STALE": "Каталог целей устарел; выводы о причинах ограничены.",
    "CAPTIVE_PORTAL_REPORTED": (
        "Сеть сообщает о возможной странице входа. Страница авторизации не подтверждена; "
        "этот сигнал сам по себе не определяет режим сети."
    ),
    "SYSTEM_RESTRICTION": _SYSTEM_RESTRICTED,
    "PROXY_AUTH_FAILED": _PROXY_AUTH,
    "VPN_SESSION_CHANGED": _TUNNEL_CHANGED,
    "HTTP_ACCESS_REJECTED": (
        "Ресурс вернул HTTP 403/429 или отклонил запрос. "
        "Возможны правила сервиса или ограничение частоты."
    ),
    "POSSIBLE_WEB_CHALLENGE": "Веб-страница, возможно, требует интерактивную защитную проверку.",
    "SYSTEM_DNS_FAILED": "Системные DNS-запросы к части целей завершились ошибкой.",
    "DNS_PATH_PROBLEM": (
        "Вероятна проблема DNS-пути: независимый DNS и подключение по его ответу сработали."
    ),
    "TLS_STAGE_FAILURE": "После успешного TCP-подключения повторно возникли ошибки TLS.",
    "IPV6_TESTS_FAILED": "Часть IPv6-проб повторно не прошла, хотя аналогичные IPv4-пробы сработали.",
    "VPN_PATH_AVAILABLE": (
        f"Проверенный ресурс ответил через {APP}, а прямые пробы завершились ошибкой."
    ),
    "POSSIBLE_ALLOWLIST": (
        "Повторные результаты по независимым сетям совместимы с возможным ограничением "
        "по белому списку."
    ),
    "ALLOWLIST_INSUFFICIENT_EVIDENCE": (
        "Часть целей отвечает, часть недоступна. Данных недостаточно, чтобы определить белый список."
    ),
    "DNS_UDP_PATH_FAILED": (
        "Повторные DNS-пробы по UDP не ответили, а DNS по TCP к тому же резолверу сработал. "
        "Это не означает блокировку всего UDP."
    ),
    "QUIC_NOT_CONFIRMED": _QUIC_FALLBACK,
    "QUIC_TEST_FAILED": "Проба QUIC завершилась ошибкой, хотя HTTPS к той же цели сработал.",
    "CONTROL_LIMITED": "Контрольный узел диагностики не ответил. Само по себе это не указывает на блокировку.",
    "NETWORK_UNVERIFIED": (
        "Базовые пробы не подтвердили доступ в интернет. "
        "Проверьте подключение перед выводами о блокировках."
    ),
}
_NO_CONCLUSION = (
    "Данных недостаточно для вывода об ограничениях. "
    "Успешные пробы относятся только к проверенным функциям."
)
_LEVELS = {
    EvidenceLevel.OBSERVED: "Наблюдаемый факт",
    EvidenceLevel.LIKELY: "Вероятное объяснение",
    EvidenceLevel.INSUFFICIENT_EVIDENCE: "Недостаточно данных",
}
_STATUSES = {
    ProbeStatus.SUCCESS: "Успешно",
    ProbeStatus.FAILURE: "Ошибка",
    ProbeStatus.UNSUPPORTED: "Не поддерживается этой проверкой",
    ProbeStatus.SKIPPED: "Пропущено",
    ProbeStatus.CANCELLED: "Отменено",
    ProbeStatus.INCONCLUSIVE: "Недостаточно данных",
}
_FAILURES = {
    F.DNS_TRUNCATED: _DNS_TRUNCATED,
    F.QUIC_FALLBACK: _QUIC_FALLBACK,
    F.ENGINE_UNAVAILABLE: "Клиент HTTP/3 с привязкой к сети недоступен в этой версии.",
    F.TRANSPORT_UNSUPPORTED: (
        f"Локальный HTTP-прокси {APP} не поддерживает эту транспортную проверку."
    ),
    F.NO_NETWORK: _NO_NETWORK,
    F.AMBIGUOUS_NETWORK: _AMBIGUOUS,
    F.PROXY_UNAVAILABLE: _NO_TUNNEL,
    F.CONTROL_UNAVAILABLE: _NO_CONTROL,
    F.NOT_IMPLEMENTED: _NO_CONTROL,
    F.DNS_FAILED: "Нет подходящего DNS-ответа для этого семейства адресов.",
    F.DEADLINE: "Достигнут лимит времени или трафика запуска.",
    F.BUDGET: "Достигнут лимит времени или трафика запуска.",
    F.TIMEOUT: "Истекло время ожидания пробы.",
    F.NETWORK_CHANGED: _NETWORK_CHANGED,
    F.VPN_SESSION_CHANGED: _TUNNEL_CHANGED,
    F.SYSTEM_RESTRICTED: _SYSTEM_RESTRICTED,
    F.PROXY_AUTH: _PROXY_AUTH,
    F.TLS_CERTIFICATE: _CERTIFICATE,
    F.UNSAFE_ADDRESS: "Полученный адрес отклонён политикой проверки публичных адресов.",
    F.HTTP_REJECTED: _FINDINGS["HTTP_ACCESS_REJECTED"],
}
_GENERIC_FAILURE = "Проба не подтвердила доступность. Сопоставьте с другими этапами."


def _counts(items) -> str:
    success = sum(o.status is ProbeStatus.SUCCESS for o in items)
    failure = sum(o.status is ProbeStatus.FAILURE for o in items)
    return f"Успешно: {success} · С ошибкой: {failure} · Не проверено: {len(items) - success - failure}"


def _observation_row(item) -> Row:
    family = item.address_family.name if item.address_family else ""
    route = "Напрямую" if item.route is ProbeRoute.DIRECT else f"Через {APP}"
    title = " · ".join(part for part in (item.target_id, item.stage.name, family, route) if part)
    tone = {ProbeStatus.SUCCESS: Tone.GOOD, ProbeStatus.FAILURE: Tone.BAD}.get(
        item.status, Tone.NEUTRAL
    )
    failure = (
        _FAILURES.get(item.failure_code, _GENERIC_FAILURE) if item.failure_code is not None else ""
    )
    return Row(title, failure, tone, _STATUSES[item.status])


def _category_summary(items) -> str:
    if all(o.failure_code is F.PROXY_UNAVAILABLE for o in items):
        return _NO_TUNNEL
    if all(o.status is ProbeStatus.UNSUPPORTED for o in items):
        return _NO_CONTROL
    if len(items) == 1 and items[0].failure_code is F.NO_NETWORK:
        return _NO_NETWORK
    if len(items) == 1 and items[0].failure_code is F.AMBIGUOUS_NETWORK:
        return _AMBIGUOUS
    return _counts(items)


def _technical_card(session: DiagnosticsSession, report: DiagnosticReport) -> Card:
    causes = session.causes
    observations = list(report.observations) + list(causes.observations if causes else ())
    findings = list(report.findings) + list(causes.findings if causes else ())
    if report.allowlist_assessment is not None:
        findings = [
            f
            for f in findings
            if f.code not in ("POSSIBLE_ALLOWLIST", "ALLOWLIST_INSUFFICIENT_EVIDENCE")
        ]
    seen: dict[tuple, Row] = {}
    for finding in findings:
        text = _FINDINGS.get(finding.code, _NO_CONCLUSION)
        seen.setdefault((finding.code, finding.level), Row(text, _LEVELS[finding.level]))
    groups: list[Group] = []
    lines: list[str] = []
    if seen:
        groups.append(Group("Что обнаружено", "", tuple(seen.values()), expanded=True))
    elif not session.running and report.allowlist_assessment is None:
        lines.append(_NO_CONCLUSION)
    lines.append(_counts(observations))
    network = next((o for o in report.observations if o.stage is ProbeStage.NETWORK), None)
    if network is not None:
        rows: tuple[Row, ...]
        if network.failure_code is not None:
            text = _FAILURES.get(network.failure_code, _GENERIC_FAILURE)
            rows = (Row(text),)
        else:
            vpn = network.evidence.get("vpnActive")
            state = _vpn_text(vpn == "true") if vpn in ("true", "false") else "Состояние неизвестно"
            rows = (Row(network_type_text(network.evidence.get("networkType"))), Row(state))
        groups.append(Group("Сеть при запуске", "", rows))

    def is_quality(item) -> bool:
        return (
            item.stage in (ProbeStage.UDP, ProbeStage.QUIC, ProbeStage.QUALITY)
            or item.evidence.get("coverage") == "dns-tcp"
        )

    def is_direct(item) -> bool:
        return (
            item.route is ProbeRoute.DIRECT
            and item.stage in (ProbeStage.TCP, ProbeStage.TLS, ProbeStage.HTTP)
            and item.evidence.get("coverage") != "dns-tcp"
        )

    for title, test in (
        (_DNS_TITLE, lambda o: o.stage is ProbeStage.DNS),
        ("Прямой доступ: TCP, TLS, HTTPS", is_direct),
        (f"Сравнение через {APP}", lambda o: o.route is ProbeRoute.ACTIVE_TUNNEL),
        ("UDP, QUIC и качество", is_quality),
    ):
        items = [o for o in observations if test(o)]
        if items:
            rows = tuple(_observation_row(o) for o in items)
            groups.append(Group(title, _category_summary(items), rows))
    return Card(
        _TECHNICAL_TITLE,
        chip=Chip(f"Измерений: {len(observations)}"),
        lines=tuple(lines),
        groups=tuple(groups),
    )


METHODOLOGY = (
    Row(
        _ALLOWLIST_TITLE,
        "Повторные HTTPS-запросы по IPv4 к ресурсам РФ и независимым зарубежным направлениям. "
        "Вывод описывает доступность проверенных ресурсов, а не доказывает причину ограничений.",
    ),
    Row(
        _SERVICES_TITLE,
        "Веб-страницы Telegram, Instagram и YouTube, публичные изображения и фрагмент видео. "
        "Сообщения, звонки и полное воспроизведение не проверяются. "
        "HTTP 403/429 не доказывает блокировку.",
    ),
    Row(
        _DNS_TITLE,
        "Сравнение DNS сети с Google и Cloudflare по HTTPS, UDP и TCP. "
        "Разные публичные IP-адреса допустимы.",
    ),
    Row(
        "Причины отказов",
        "При отказах приложение само проверяет TCP и TLS для недоступных ресурсов и контрольных "
        "сайтов, только IPv4. Это наблюдения, а не доказанная блокировка. "
        "HTTP/3 показывается в техническом отчёте.",
    ),
    Row(
        f"Напрямую и через {APP}",
        f"Основные пробы идут напрямую, даже при подключённом {APP}. Сравнение через {APP} "
        "использует его локальный HTTP-прокси и не проверяет маршруты других приложений.",
    ),
    Row(
        "Время и трафик",
        "Запуск вручную. До 3 минут и 8 МиБ данных плюс служебный трафик. "
        "Настройки сети не меняются.",
    ),
    Row(
        "Приватность отчёта",
        "Отчёт содержит результаты и коды ошибок без имён сетей, IP-адресов и данных серверов. "
        "Файл сохраняется только по вашей команде.",
    ),
)


# Сборка


def _verdict_notes(session: DiagnosticsSession, report, summary: DiagnosticSummary) -> list[str]:
    notes: list[str] = []
    if summary.verdict is SummaryVerdict.MIXED_NETWORKS:
        notes.append("Проверьте сеть целиком ещё раз.")
    if summary.verdict is SummaryVerdict.UNKNOWN:
        source = session.report_for(DiagnosticSection.ALLOWLIST)
        assessment = source.allowlist_assessment if source else None
        if assessment is not None and assessment.reasons:
            notes.append(_ALLOWLIST_REASONS[assessment.reasons[0]])
    if summary.incomplete:
        notes.append("Проверка не завершена")
    if report.termination is DiagnosticTermination.NETWORK_CHANGED:
        notes.append(_NETWORK_CHANGED)
    elif report.termination is DiagnosticTermination.DEADLINE:
        notes.append("Достигнут лимит времени. Результаты неполные.")
    elif report.is_partial:
        notes.append("Проверка остановлена. Результаты неполные.")
    return notes


def _state_rows(session: DiagnosticsSession) -> tuple[tuple[str, Chip], ...]:
    rows = []
    allowlist = session.report_for(DiagnosticSection.ALLOWLIST)
    if allowlist is not None and allowlist.allowlist_assessment is not None:
        rows.append((_ALLOWLIST_TITLE, _allowlist_chip(allowlist.allowlist_assessment)))
    services = session.report_for(DiagnosticSection.SERVICES)
    if services is not None and services.service_assessment is not None:
        chip = _service_chip(services.service_assessment) or Chip("Не удалось проверить")
        rows.append(("Сервисы", chip))
    dns = session.report_for(DiagnosticSection.DNS)
    if dns is not None and dns.dns_assessment is not None:
        rows.append((_DNS_TITLE, _dns_chip(dns.dns_assessment)))
    return tuple(rows)


def _causes_text(session: DiagnosticsSession) -> str | None:
    assessment = session.causes.cause_assessment if session.causes else None
    if assessment is None or not assessment.top_causes:
        return None
    names = "; ".join(cause_text(c) for c in assessment.top_causes)
    count, total = assessment.top_cause_count, assessment.total
    if len(assessment.top_causes) > 1:
        return f"Поровну, по {count} из {total}: {names}"
    return f"Чаще всего: {names} ({count} из {total})"


def _actions(session: DiagnosticsSession, report) -> tuple[Action, ...]:
    reports = [report, *session.previous_reports.values()]
    if session.causes is not None:
        reports.append(session.causes)
    codes = dict.fromkeys(
        code
        for item in reports
        for finding in item.findings
        for code in finding.recommendation_codes
    )
    # Метки у OPEN_WIFI_LOGIN и CHECK_SYSTEM_NETWORK совпадают: двух одинаковых кнопок не нужно.
    by_label = {}
    for code in codes:
        by_label.setdefault(recommendation_text(code), code)
    return tuple(
        Action(code, label, index == 0) for index, (label, code) in enumerate(by_label.items())
    )


def _has_restricted(session: DiagnosticsSession, report) -> bool:
    return any(
        o.status is ProbeStatus.SKIPPED and o.failure_code is F.SYSTEM_RESTRICTED
        for o in report.observations
    )


def _section_running(session: DiagnosticsSession, section: DiagnosticSection) -> bool:
    active = session.active_section
    return session.running and not session.causes_running and (active is None or active is section)


def diagnostics_view(session: DiagnosticsSession) -> DiagnosticsView:
    report = session.report
    if session.running:
        primary = STOP
    elif session.active_section is not None:
        primary = START_ALL
    else:
        primary = START
    if report is None and not session.running:
        return DiagnosticsView(primary, False, idle=True, methodology=METHODOLOGY)
    network = None
    chips: list[Chip] = []
    facts = report.network_facts() if report is not None else None
    if facts is not None:
        network = network_type_text(facts.type)
        if facts.vpn_active is not None:
            chips.append(Chip(_vpn_text(facts.vpn_active)))
    scope = None
    if session.active_section is not None:
        scope = f"Этот запуск: {_SECTIONS[session.active_section]}"
    causes = (
        session.causes.cause_assessment.causes
        if session.causes is not None and session.causes.cause_assessment is not None
        else {}
    )
    cards = []
    allowlist = session.report_for(DiagnosticSection.ALLOWLIST)
    if allowlist is not None and allowlist.allowlist_assessment is not None:
        running = _section_running(session, DiagnosticSection.ALLOWLIST)
        cards.append(_allowlist_card(session, allowlist.allowlist_assessment, running, causes))
    services = session.report_for(DiagnosticSection.SERVICES)
    if services is not None and services.service_assessment is not None:
        running = _section_running(session, DiagnosticSection.SERVICES)
        cards.append(_service_card(session, services.service_assessment, running, causes))
    dns = session.report_for(DiagnosticSection.DNS)
    if dns is not None and dns.dns_assessment is not None:
        running = _section_running(session, DiagnosticSection.DNS)
        cards.append(_dns_card(session, dns.dns_assessment, running))
    summary = session.summary()
    verdict = None
    notes: tuple[str, ...] = ()
    rows: tuple[tuple[str, Chip], ...] = ()
    actions: tuple[Action, ...] = ()
    progress = None
    if session.running and not session.causes_running:
        count = len(report.observations) if report is not None else 0
        progress = f"Завершено проб: {count}. Выводы предварительные."
    elif summary is not None and report is not None:
        hidden = len(dns.dns_assessment.affected_hosts) if dns and dns.dns_assessment else 0
        verdict = summary_verdict_label(summary, hidden)
        notes = tuple(_verdict_notes(session, report, summary))
        rows = _state_rows(session)
        if not session.running:
            actions = _actions(session, report)
    technical = None
    footnotes: list[str] = []
    warning = None
    if report is not None:
        technical = _technical_card(session, report)
        if session.active_section is not None and not session.running:
            footnotes.append(
                "Технические результаты, выводы и экспорт относятся только к последнему "
                "запуску выбранного этапа."
            )
        if any(
            o.stage is ProbeStage.QUALITY and o.status is ProbeStatus.UNSUPPORTED
            for o in report.observations
        ):
            footnotes.append(
                "UDP echo и оценка качества недоступны без контрольных узлов. "
                "DNS по UDP/TCP и HTTP/3 показаны отдельно."
            )
        if _has_restricted(session, report):
            warning = _SYSTEM_RESTRICTED
    return DiagnosticsView(
        primary,
        session.running,
        network=network,
        chips=tuple(chips),
        scope=scope,
        warning=warning,
        progress_text=progress,
        verdict=verdict,
        verdict_notes=notes,
        state_rows=rows,
        causes_running=session.causes_running,
        causes_text=None if session.causes_running else _causes_text(session),
        actions=actions,
        can_copy=session.can_copy and summary is not None,
        can_export=session.can_export,
        error=(
            "Не удалось завершить диагностику. Частичные результаты сохранены. "
            "Повторите проверку при стабильной сети."
            if session.failed
            else None
        ),
        cards=tuple(cards),
        technical=technical,
        footnotes=tuple(footnotes),
        methodology=METHODOLOGY,
    )


class ViewUpdater:
    """Пересчитывает представление не чаще раза в `interval_ms` и зовёт `render` при изменении.

    За три минуты приходят сотни наблюдений, а окно перестраивает виджеты целиком: каждое
    перестроение на каждое наблюдение заметно тормозило бы главный поток.
    """

    def __init__(self, session, loop, render, interval_ms=300, clock=time.monotonic):
        self._session = session
        self._loop = loop
        self._render = render
        self._interval = interval_ms / 1000
        self._interval_ms = interval_ms
        self._clock = clock
        self._last = float("-inf")
        self._timer: object | None = None
        self.view: DiagnosticsView | None = None

    def attach(self) -> None:
        self._session.on_changed = self.changed
        self._flush()

    def detach(self) -> None:
        self._cancel()
        if self._session.on_changed == self.changed:
            self._session.on_changed = None

    def changed(self) -> None:
        if self._timer is not None:
            return
        if self._clock() - self._last >= self._interval:
            self._flush()
        else:
            self._timer = self._loop.schedule(self._interval_ms, self._on_timer)

    def _on_timer(self) -> bool:
        self._timer = None
        self._flush()
        return False

    def _cancel(self) -> None:
        if self._timer is not None:
            self._loop.cancel(self._timer)
            self._timer = None

    def _flush(self) -> None:
        self._last = self._clock()
        view = diagnostics_view(self._session)
        if view != self.view:
            self.view = view
            self._render(view)


# Текст для чата поддержки


def local_time() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def _mid_sentence(text: str) -> str:
    """«DNS» и другие сокращения внутри фразы сохраняют регистр."""
    if len(text) > 1 and text[1].islower():
        return text[0].lower() + text[1:]
    return text


class RussianSummaryStrings:
    """Строки `build_summary_text`; `hidden_domains` нужен подписи вывода по DNS."""

    def __init__(self, hidden_domains: int = 0):
        self._hidden = hidden_domains

    def title(self, app_version: str, time: str) -> str:
        return f"{TITLE} · {APP} {app_version} · {time}"

    def network(self, facts: DiagnosticNetworkFacts | None) -> str:
        parts = [network_type_text(facts.type if facts else None)]
        if facts is not None and facts.vpn_active is not None:
            parts.append(_vpn_text(facts.vpn_active))
        return f"Сеть: {', '.join(parts)}"

    def verdict(self, summary: DiagnosticSummary) -> str:
        return f"Итог: {_mid_sentence(summary_verdict_label(summary, self._hidden))}"

    def allowlist(self, verdict, ru_ok, ru_total, other_ok, other_total) -> str:
        label = _mid_sentence(_ALLOWLIST_LABELS[verdict])
        return f"Белые списки: {label} (РФ-ресурсы {ru_ok}/{ru_total}, другие {other_ok}/{other_total})"

    def services(self, available, total, per_service) -> str:
        details = ", ".join(f"{name} {ok}/{count}" for name, ok, count in per_service)
        return f"Сервисы напрямую: {available} из {total} ({details})"

    def dns(self, verdict, system, public, secure) -> str:
        label = dns_verdict_label(verdict, self._hidden)
        # Большинство подписей уже называют DNS: приставка дала бы «DNS: DNS работает».
        head = label if "DNS" in label else f"DNS: {_mid_sentence(label)}"
        return (
            f"{head} (сети {system[0]}/{system[1]}, публичный {public[0]}/{public[1]}, "
            f"DoH {secure[0]}/{secure[1]})"
        )

    def causes(self, causes, count, total) -> str:
        names = "; ".join(cause_text(c) for c in causes)
        if len(causes) > 1:
            return f"Причины поровну, по {count} из {total}: {names}"
        return f"Причины: чаще всего {names} ({count} из {total})"

    def state(self, incomplete, section, probes) -> str:
        if section is not None:
            return f"Повтор этапа: {_SECTIONS[section]}, проб: {probes}"
        if incomplete:
            return f"Проверка остановлена, проб: {probes}"
        return f"Проверка завершена, проб: {probes}"


def summary_text(session: DiagnosticsSession) -> str | None:
    summary = session.summary()
    if summary is None or session.report is None:
        return None
    dns = session.report_for(DiagnosticSection.DNS)
    hidden = len(dns.dns_assessment.affected_hosts) if dns and dns.dns_assessment else 0
    return build_summary_text(
        summary,
        session.report,
        local_time(),
        RussianSummaryStrings(hidden),
        cause_report=session.causes,
    )
