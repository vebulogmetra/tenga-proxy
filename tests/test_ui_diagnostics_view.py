"""Представление окна диагностики: что и какими словами увидит пользователь."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass

import pytest

from src.diag.assess import recommendations as rec
from src.diag.assess.summary import DiagnosticSummary, SummaryVerdict
from src.diag.catalog import DiagnosticPurpose as P
from src.diag.models import (
    AddressFamily,
    AllowlistAssessment,
    AllowlistFamilyResult,
    AllowlistReason,
    AllowlistSiteResult,
    AllowlistSiteState,
    AllowlistVerdict,
    CauseAssessment,
    DiagnosticFailure,
    DiagnosticFinding,
    DiagnosticReport,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
    DnsAssessment,
    DnsCheck,
    DnsCheckStatus,
    DnsVerdict,
    EvidenceLevel,
    FailureCause,
    ProbeObservation,
    ProbeRoute,
    ProbeStage,
    ProbeStatus,
    PublicDnsFact,
    SecureDnsFact,
    ServiceAssessment,
    ServiceCheck,
    ServiceCheckStatus,
    ServiceRoute,
    SystemDnsFact,
)
from src.ui.logic.diagnostics_session import DiagnosticsSession
from src.ui.logic.diagnostics_view import (
    RussianSummaryStrings,
    Tone,
    diagnostics_view,
    recommendation_text,
    summary_text,
)


def network(kind="WIFI", vpn="true"):
    return ProbeObservation(
        "network", "network", ProbeRoute.DIRECT, ProbeStage.NETWORK, ProbeStatus.SUCCESS,
        evidence={"networkType": kind, "vpnActive": vpn},
    )  # fmt: skip


def allowlist(verdict=AllowlistVerdict.POSSIBLE, completed=True, reasons=(), sites=None):
    sites = sites or (
        AllowlistSiteResult("ya", "ya.ru", AllowlistSiteState.AVAILABLE, True),
        AllowlistSiteResult("gh", "github.com", AllowlistSiteState.UNAVAILABLE),
    )
    family = AllowlistFamilyResult(AddressFamily.IPV4, 1, 1, 1, 1, sites, ())
    return AllowlistAssessment(
        verdict, (family,), reasons, checked_sites=1, total_sites=2, completed=completed
    )


def services(
    completed=True,
    status=ServiceCheckStatus.UNAVAILABLE,
    failure=DiagnosticFailure.TIMEOUT,
    routes=None,
):
    check = ServiceCheck("tg-web", P.TELEGRAM_WEB, status, failure=failure, completed=completed)
    return ServiceAssessment(
        True, completed, 1, 1, routes or (ServiceRoute(ProbeRoute.DIRECT, (check,)),)
    )


def dns(verdict=DnsVerdict.WORKING, completed=True, started=True, hosts=(), checks=None):
    return DnsAssessment(
        verdict, started, completed, 1, 1,
        checks if checks is not None else (
            DnsCheck("example.com", "system", DnsCheckStatus.AVAILABLE, family=AddressFamily.IPV4),
            DnsCheck("example.com", "system", DnsCheckStatus.UNKNOWN, family=AddressFamily.IPV6),
        ),
        system_dns=SystemDnsFact.ANSWERS, public_dns=PublicDnsFact.REACHES,
        secure_dns=SecureDnsFact.AVAILABLE, affected_hosts=hosts,
    )  # fmt: skip


def report(section=None, termination=DiagnosticTermination.COMPLETED, obs=None, **kwargs):
    return DiagnosticReport(
        DiagnosticRunContext("run", "1", "1.2.3", section=section),
        tuple(obs if obs is not None else (network(),)),
        termination=termination,
        **kwargs,
    )


def session_with(main=None, **fields_) -> DiagnosticsSession:
    session = DiagnosticsSession(None, lambda: None)
    session.report = main
    for name, value in fields_.items():
        setattr(session, name, value)
    return session


def full():
    return report(
        allowlist_assessment=allowlist(), service_assessment=services(), dns_assessment=dns()
    )


def test_idle_shows_only_the_start_button():
    view = diagnostics_view(session_with())
    assert view.idle
    assert view.primary_label == "Проверить сеть"
    assert view.cards == ()
    assert not view.can_copy
    assert not view.can_export
    assert view.technical is None
    assert view.methodology


def test_running_without_report_shows_progress_and_stop():
    view = diagnostics_view(session_with(running=True))
    assert not view.idle
    assert view.primary_label == "Остановить"
    assert view.progress_text == "Завершено проб: 0. Выводы предварительные."
    assert view.verdict is None


def test_finished_report_has_cards_in_order_and_header():
    view = diagnostics_view(session_with(full()))
    assert [c.title for c in view.cards] == ["Белые списки", "Доступ к сервисам", "DNS"]
    assert view.network == "Wi-Fi"
    assert [c.text for c in view.chips] == ["Veblock подключён"]
    assert view.verdict == "Похоже, оператор включил белые списки"
    assert view.can_copy
    assert view.can_export
    assert view.technical.title == "Технические результаты"


@pytest.mark.parametrize(
    ("kind", "label"), [("ETHERNET", "Ethernet"), ("OTHER", "Другая сеть"), ("WIFI", "Wi-Fi")]
)
def test_network_type_labels(kind, label):
    view = diagnostics_view(session_with(report(obs=[network(kind, "false")])))
    assert view.network == label
    assert view.chips[0].text == "Veblock отключён"


def test_chip_tones():
    view = diagnostics_view(session_with(full()))
    allow, serv, dns_card = view.cards
    assert allow.chip.tone is Tone.BAD
    assert serv.chip.text == "0 из 1"
    assert serv.chip.tone is Tone.BAD
    assert dns_card.chip.text == "DNS работает без вмешательства"
    assert dns_card.chip.tone is Tone.GOOD


def test_unfinished_stage_has_no_chip_and_shows_progress():
    main = report(
        allowlist_assessment=allowlist(completed=False),
        service_assessment=services(completed=False, status=ServiceCheckStatus.UNKNOWN),
        dns_assessment=dns(completed=False, started=False),
    )
    allow, serv, dns_card = diagnostics_view(session_with(main, running=True)).cards
    assert allow.chip is None
    assert allow.progress == 0.5
    assert "Проверено 1 из 2" in allow.lines
    assert serv.chip is None
    assert serv.progress == 1.0
    assert serv.groups[0].rows[0].value == "Проверяется"
    assert dns_card.chip is None
    assert dns_card.lines == ("После проверки сервисов",)
    assert not allow.retry_enabled


def test_dns_card_has_three_facts_and_hides_answered_aaaa():
    card = diagnostics_view(session_with(full())).cards[2]
    facts = card.groups[0]
    assert [r.title for r in facts.rows] == ["DNS сети", "Публичный DNS", "Защищённый DNS"]
    assert [r.value for r in facts.rows] == ["отвечает", "запросы доходят", "доступен"]
    assert facts.expanded
    system = card.groups[1]
    assert system.summary == "Успешно: 1 из 1"
    assert [r.title for r in system.rows] == ["example.com · A (IPv4)"]


@pytest.mark.parametrize(
    ("verdict", "fragment"),
    [
        (DnsVerdict.SPOOFING, "Сеть возвращает ложный адрес для: a.ru"),
        (DnsVerdict.DOMAINS_HIDDEN, "защищённый DNS их находит: a.ru"),
        (DnsVerdict.WORKING_DOH_BLOCKED, "На работу Veblock это не влияет."),
        (DnsVerdict.UNKNOWN, "Не удалось отделить проблему DNS"),
    ],
)
def test_dns_lines(verdict, fragment):
    main = report(dns_assessment=dns(verdict, hosts=("a.ru",)))
    card = diagnostics_view(session_with(main)).cards[0]
    assert any(fragment in line for line in card.lines)


@pytest.mark.parametrize(
    ("rcode", "failure", "text"),
    [
        ("3", DiagnosticFailure.DNS_FAILED, "NXDOMAIN"),
        ("2", DiagnosticFailure.DNS_FAILED, "SERVFAIL"),
        ("0", DiagnosticFailure.DNS_FAILED, "Запись этого типа не получена"),
        (None, DiagnosticFailure.TIMEOUT, "не ответил вовремя"),
        (None, DiagnosticFailure.SYSTEM_RESTRICTED, "Прямые запросы закрыты"),
    ],
)
def test_dns_failure_reasons(rcode, failure, text):
    check = DnsCheck("a", "system", DnsCheckStatus.UNAVAILABLE, failure, rcode, AddressFamily.IPV4)
    main = report(dns_assessment=dns(checks=(check,)))
    system = diagnostics_view(session_with(main)).cards[0].groups[1]
    assert text in system.rows[0].subtitle
    assert system.rows[0].tone is Tone.BAD
    assert text in system.summary


def test_cause_replaces_restated_service_reason():
    causes = report(
        DiagnosticSection.DETAILS,
        cause_assessment=CauseAssessment({"tg-web": FailureCause.TLS_FAILED}, 1),
    )
    card = diagnostics_view(session_with(full(), causes=causes)).cards[1]
    row = card.groups[0].rows[0]
    assert row.subtitle == "Соединение обрывается при TLS"
    assert row.value == "Недоступен"


def test_after_handshake_cause_keeps_the_reason():
    causes = report(
        DiagnosticSection.DETAILS,
        cause_assessment=CauseAssessment({"tg-web": FailureCause.AFTER_HANDSHAKE}, 1),
    )
    row = diagnostics_view(session_with(full(), causes=causes)).cards[1].groups[0].rows[0]
    assert row.subtitle == "Ресурс не ответил вовремя · Сбой после установки соединения"


def test_http_status_is_not_called_a_blockage():
    check = ServiceCheck(
        "tg-web", P.TELEGRAM_WEB, ServiceCheckStatus.UNKNOWN, http_status=403, completed=True
    )
    route = ServiceRoute(ProbeRoute.DIRECT, (check,))
    main = report(service_assessment=services(routes=(route,)))
    row = diagnostics_view(session_with(main)).cards[0].groups[0].rows[0]
    assert "HTTP 403" in row.subtitle
    assert "не подтверждает" in row.subtitle


def test_tunnel_without_proxy_is_one_line_not_a_list():
    direct = ServiceRoute(ProbeRoute.DIRECT, ())
    tunnel = ServiceRoute(
        ProbeRoute.ACTIVE_TUNNEL,
        (
            ServiceCheck(
                "tg-web", P.TELEGRAM_WEB, ServiceCheckStatus.UNKNOWN,
                failure=DiagnosticFailure.PROXY_UNAVAILABLE,
            ),
        ),
    )  # fmt: skip
    card = diagnostics_view(
        session_with(report(service_assessment=services(routes=(direct, tunnel))))
    ).cards[0]
    assert "Veblock не подключён: сравнение через туннель пропущено." in card.lines
    assert card.groups == ()


def test_tunnel_comparison_is_labelled_with_app_name():
    check = ServiceCheck("tg-web", P.TELEGRAM_WEB, ServiceCheckStatus.AVAILABLE, completed=True)
    routes = (ServiceRoute(ProbeRoute.ACTIVE_TUNNEL, (check,)),)
    card = diagnostics_view(session_with(report(service_assessment=services(routes=routes)))).cards[
        0
    ]
    assert card.groups[0].title == "Через Veblock · Telegram"


def test_system_restriction_warning():
    skipped = ProbeObservation(
        "a", "a", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.SKIPPED,
        failure_code=DiagnosticFailure.SYSTEM_RESTRICTED,
    )  # fmt: skip
    view = diagnostics_view(session_with(report(obs=[network(), skipped])))
    assert "Прямые запросы закрыты" in view.warning


@pytest.mark.parametrize(
    ("termination", "text"),
    [
        (DiagnosticTermination.NETWORK_CHANGED, "Сеть изменилась"),
        (DiagnosticTermination.DEADLINE, "Достигнут лимит времени"),
        (DiagnosticTermination.USER_CANCELLED, "Проверка остановлена"),
    ],
)
def test_partial_reports_say_so(termination, text):
    view = diagnostics_view(session_with(report(termination=termination)))
    assert "Проверка не завершена" in view.verdict_notes
    assert any(text in note for note in view.verdict_notes)


def test_section_retry_marks_previous_and_offers_full_check():
    first = full()
    second = report(DiagnosticSection.DNS, dns_assessment=dns())
    session = session_with(
        second,
        active_section=DiagnosticSection.DNS,
        previous_reports={
            DiagnosticSection.ALLOWLIST: first,
            DiagnosticSection.SERVICES: first,
        },
    )
    view = diagnostics_view(session)
    assert view.primary_label == "Проверить всю сеть"
    assert view.scope == "Этот запуск: DNS"
    assert [c.previous for c in view.cards] == [True, True, False]
    assert all(c.retry_enabled for c in view.cards)
    assert view.footnotes[0].startswith("Технические результаты")


def test_recommendations_become_deduplicated_actions():
    finding = DiagnosticFinding(
        "X",
        EvidenceLevel.LIKELY,
        ("network",),
        (rec.CHECK_SYSTEM_DNS, rec.USE_ACTIVE_VPN, rec.CHECK_SYSTEM_DNS),
    )
    view = diagnostics_view(session_with(report(findings=(finding,))))
    assert [(a.code, a.label, a.primary) for a in view.actions] == [
        (rec.CHECK_SYSTEM_DNS, "Настройки DNS", True),
        (rec.USE_ACTIVE_VPN, "Подключить Veblock", False),
    ]


def test_actions_are_hidden_while_causes_run():
    finding = DiagnosticFinding("X", EvidenceLevel.LIKELY, ("network",), (rec.RETRY_LATER,))
    main = report(findings=(finding,))
    view = diagnostics_view(session_with(main, running=True, causes_running=True))
    assert view.verdict is not None
    assert view.causes_running
    assert view.actions == ()


def test_causes_text_top_and_tie():
    top = CauseAssessment(
        {
            "a": FailureCause.CERTIFICATE,
            "b": FailureCause.CERTIFICATE,
            "c": FailureCause.TLS_FAILED,
        },
        3,
    )
    view = diagnostics_view(session_with(full(), causes=report(cause_assessment=top)))
    assert view.causes_text == "Чаще всего: сертификат не прошёл проверку (2 из 3)"
    tie = CauseAssessment({"a": FailureCause.CERTIFICATE, "c": FailureCause.TLS_FAILED}, 2)
    view = diagnostics_view(session_with(full(), causes=report(cause_assessment=tie)))
    assert view.causes_text.startswith("Поровну, по 1 из 2: ")


def test_technical_card_hides_allowlist_findings_and_counts_probes():
    findings = (
        DiagnosticFinding("POSSIBLE_ALLOWLIST", EvidenceLevel.LIKELY, ("network",)),
        DiagnosticFinding("TLS_STAGE_FAILURE", EvidenceLevel.OBSERVED, ("network",)),
    )
    main = report(allowlist_assessment=allowlist(), findings=findings)
    tech = diagnostics_view(session_with(main)).technical
    assert tech.chip.text == "Измерений: 1"
    found = tech.groups[0]
    assert found.title == "Что обнаружено"
    assert [r.subtitle for r in found.rows] == ["Наблюдаемый факт"]
    assert "Успешно: 1 · С ошибкой: 0 · Не проверено: 0" in tech.lines


def test_technical_card_has_observation_rows():
    item = ProbeObservation(
        "h", "tg-web", ProbeRoute.DIRECT, ProbeStage.HTTP, ProbeStatus.FAILURE,
        failure_code=DiagnosticFailure.TIMEOUT, address_family=AddressFamily.IPV4,
    )  # fmt: skip
    tech = diagnostics_view(session_with(report(obs=[network(), item]))).technical
    direct = next(g for g in tech.groups if g.title.startswith("Прямой доступ"))
    assert direct.rows[0].title == "tg-web · HTTP · IPV4 · Напрямую"
    assert direct.rows[0].value == "Ошибка"
    assert direct.rows[0].subtitle == "Истекло время ожидания пробы."


def test_view_compares_by_value():
    session = session_with(full())
    assert diagnostics_view(session) == diagnostics_view(session)


def test_failed_run_shows_error():
    view = diagnostics_view(session_with(report(), failed=True))
    assert "Частичные результаты сохранены" in view.error


def _strings_of(value):
    if isinstance(value, str):
        yield value
    elif is_dataclass(value):
        for item in fields(value):
            yield from _strings_of(getattr(value, item.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _strings_of(item)


def test_vocabulary_has_no_android_words():
    findings = (DiagnosticFinding("VPN_PATH_AVAILABLE", EvidenceLevel.LIKELY, ("network",)),)
    view = diagnostics_view(session_with(full(), findings=(), failed=True))
    other = diagnostics_view(
        session_with(report(findings=findings, allowlist_assessment=allowlist()))
    )
    text = "\n".join([*_strings_of(view), *_strings_of(other)])
    for word in ("профил", "Android", "Частный DNS", "VPN-"):
        assert word not in text
    assert not re.search(r"\bVPN\b", text)


@pytest.mark.parametrize(
    "code",
    [
        rec.CHECK_SYSTEM_DNS, rec.OPEN_WIFI_LOGIN, rec.USE_ACTIVE_VPN, rec.TRY_OTHER_PROFILE,
        rec.REPEAT_STABLE_NETWORK, rec.RETRY_LATER, rec.CHECK_SYSTEM_NETWORK,
    ],
)  # fmt: skip
def test_recommendation_labels_use_desktop_words(code):
    label = recommendation_text(code)
    assert label
    assert "VPN" not in label
    assert "профил" not in label.lower()


def test_summary_text_is_readable(monkeypatch):
    monkeypatch.setattr("src.ui.logic.diagnostics_view.local_time", lambda: "05.11.2026 12:00")
    text = summary_text(session_with(full()))
    assert text.splitlines() == [
        "Диагностика сети · Veblock 1.2.3 · 05.11.2026 12:00",
        "Сеть: Wi-Fi, Veblock подключён",
        "Итог: похоже, оператор включил белые списки",
        "Белые списки: включены (РФ-ресурсы 1/1, другие 0/1)",
        "Сервисы напрямую: 0 из 1 (Telegram 0/1)",
        "DNS работает без вмешательства (сети 1/1, публичный 0/0, DoH 0/0)",
        "Проверка завершена, проб: 1",
    ]


def test_summary_text_is_none_without_report():
    assert summary_text(session_with()) is None


def test_dns_label_without_the_word_gets_a_prefix():
    strings = RussianSummaryStrings()
    line = strings.dns(DnsVerdict.UNKNOWN, (0, 1), (0, 1), (0, 1))
    assert line.startswith("DNS: не удалось проверить")


def test_verdict_keeps_acronym_case():
    strings = RussianSummaryStrings(2)
    summary = DiagnosticSummary(SummaryVerdict.DNS_PROBLEM, (), DnsVerdict.DOMAINS_HIDDEN, False)
    assert strings.verdict(summary) == "Итог: DNS-блокировка: скрыто доменов — 2"


def test_allowlist_reason_appears_in_insufficient_card():
    main = report(
        allowlist_assessment=allowlist(
            AllowlistVerdict.INSUFFICIENT, reasons=(AllowlistReason.SYSTEM_RESTRICTED,)
        )
    )
    card = diagnostics_view(session_with(main)).cards[0]
    assert card.chip.text == "Не удалось определить"
    assert "Прямые запросы закрыты; доступность ресурсов нельзя оценить надёжно." in card.lines
    assert card.lines[-1] == "Повторите проверку при стабильном подключении."


class _Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_updater_throttles_and_flushes_last_state():
    from src.core.main_loop import ImmediateLoop
    from src.ui.logic.diagnostics_view import ViewUpdater

    session = session_with()
    loop = ImmediateLoop()
    clock = _Clock()
    rendered = []
    updater = ViewUpdater(session, loop, rendered.append, clock=clock)
    updater.attach()
    assert len(rendered) == 1
    session.report = report()
    session.on_changed()
    assert len(rendered) == 1  # слишком рано: ждёт таймер
    assert len(loop.scheduled) == 1
    session.on_changed()
    assert len(loop.scheduled) == 1  # второй таймер не нужен
    clock.now = 1.0
    loop.fire()
    assert len(rendered) == 2
    assert rendered[-1].network == "Wi-Fi"


def test_updater_skips_unchanged_view_and_detaches():
    from src.core.main_loop import ImmediateLoop
    from src.ui.logic.diagnostics_view import ViewUpdater

    session = session_with()
    clock = _Clock()
    rendered = []
    updater = ViewUpdater(session, ImmediateLoop(), rendered.append, clock=clock)
    updater.attach()
    clock.now = 10.0
    session.on_changed()
    assert len(rendered) == 1
    updater.detach()
    assert session.on_changed is None
