"""Состояние окна «Диагностика сети»: порт NetworkDiagnosticsViewModel без тулкита.

Поля меняются только в главном потоке. Проверка идёт в фоновом потоке, её события копятся в
очереди и применяются одним `dispatch`: сотни наблюдений не должны стать сотнями перерисовок.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from src.core.main_loop import MainLoop
from src.diag.assess.services import PURPOSES as SERVICE_PURPOSES
from src.diag.assess.summary import DiagnosticSummary, summarize
from src.diag.catalog import DiagnosticPurpose, DiagnosticTarget
from src.diag.export import write_report
from src.diag.models import (
    MAX_DETAIL_TARGETS,
    DiagnosticReport,
    DiagnosticRequest,
    DiagnosticRunContext,
    DiagnosticSection,
    DiagnosticTermination,
)
from src.diag.runner import (
    DiagnosticRunner,
    Finished,
    ObservationEvent,
    Started,
    Updated,
    causes_request,
    failed_target_ids,
    same_network,
)

logger = logging.getLogger("tenga.diag")

RESULT_SECTIONS = (DiagnosticSection.ALLOWLIST, DiagnosticSection.SERVICES, DiagnosticSection.DNS)
_HELPERS = (DiagnosticPurpose.BASELINE, DiagnosticPurpose.CONTROL)


def _failed_targets(
    allowlist: DiagnosticReport | None,
    services: DiagnosticReport | None,
    targets: tuple[DiagnosticTarget, ...],
) -> frozenset[str]:
    """Помощники считаются по отчёту белых списков, сервисы — по своему: при повторе это разные
    запуски, а целевые наборы не пересекаются."""
    failed: set[str] = set()
    if allowlist is not None:
        helpers = [t for t in targets if t.purpose in _HELPERS]
        failed |= failed_target_ids(allowlist, helpers)
    if services is not None:
        checked = [t for t in targets if t.purpose in SERVICE_PURPOSES]
        failed |= failed_target_ids(services, checked)
    return frozenset(sorted(failed)[:MAX_DETAIL_TARGETS])


class DiagnosticsSession:
    def __init__(
        self,
        loop: MainLoop,
        runner_factory: Callable[[], DiagnosticRunner],
        epoch_seconds: Callable[[], float] = time.time,
    ):
        self._loop = loop
        self._runner_factory = runner_factory
        self._epoch_seconds = epoch_seconds
        self.on_changed: Callable[[], None] | None = None
        self.running = False
        self.failed = False
        self.report: DiagnosticReport | None = None
        self.targets: tuple[DiagnosticTarget, ...] = ()
        self.active_section: DiagnosticSection | None = None
        self.previous_reports: dict[DiagnosticSection, DiagnosticReport] = {}
        self.causes: DiagnosticReport | None = None
        self.causes_running = False
        self._runner: DiagnosticRunner | None = None
        # Поколение отсекает события остановленного запуска: у него свой поток и свой runner.
        self._generation = 0
        self._lock = threading.Lock()
        self._pending: list[tuple[int, Callable[[], None]]] = []
        self._drain_scheduled = False

    # Что доступно

    @property
    def can_start(self) -> bool:
        return not self.running

    @property
    def can_stop(self) -> bool:
        return self.running

    @property
    def can_export(self) -> bool:
        return not self.running and self.report is not None

    @property
    def can_copy(self) -> bool:
        return self.can_export

    # Отчёты по этапам

    def report_for(self, section: DiagnosticSection) -> DiagnosticReport | None:
        if self.active_section is None or self.active_section is section:
            return self.report
        return self.previous_reports.get(section)

    def is_previous(self, section: DiagnosticSection) -> bool:
        return (
            self.active_section is not None
            and self.active_section is not section
            and section in self.previous_reports
        )

    def summary(self) -> DiagnosticSummary | None:
        """Пока идёт основная проверка, вывода нет: промежуточный прочитали бы как итог."""
        if self.report is None or (self.running and not self.causes_running):
            return None
        allowlist = self.report_for(DiagnosticSection.ALLOWLIST)
        services = self.report_for(DiagnosticSection.SERVICES)
        dns = self.report_for(DiagnosticSection.DNS)
        types = []
        for item in (allowlist, services, dns):
            facts = item.network_facts() if item is not None else None
            types.append(facts.type if facts else None)
        return summarize(
            allowlist.allowlist_assessment if allowlist else None,
            services.service_assessment if services else None,
            dns.dns_assessment if dns else None,
            types,
            self.report.is_partial,
        )

    # Команды

    def start(self, section: DiagnosticSection | None = None) -> bool:
        """False — проверка уже идёт: вторая одновременная исказила бы обе."""
        if self.running:
            return False
        previous = {}
        if section is not None:
            for key in RESULT_SECTIONS:
                earlier = self.report_for(key)
                if earlier is not None:
                    previous[key] = earlier
        kept_causes = self.causes if section is DiagnosticSection.DNS else None
        self._generation += 1
        generation = self._generation
        self.running = True
        self.failed = False
        self.report = None
        self.targets = ()
        self.active_section = section
        self.previous_reports = previous
        self.causes = kept_causes
        self.causes_running = False
        runner = self._runner_factory()
        self._runner = runner
        threading.Thread(
            target=self._work,
            args=(generation, runner, section, previous),
            daemon=True,
            name="diag-session",
        ).start()
        self._notify()
        return True

    def stop(self, reason: DiagnosticTermination = DiagnosticTermination.USER_CANCELLED) -> None:
        if not self.running:
            return
        self._generation += 1
        if self.causes_running:
            if self.causes is not None:
                self.causes = replace(self.causes, termination=reason)
        elif self.report is not None:
            self.report = replace(self.report, termination=reason)
        else:
            # Окружение ещё открывается: отчёт нужен, чтобы окно показало остановку, а не простой.
            self.report = DiagnosticReport(
                DiagnosticRunContext(
                    DiagnosticRunContext.new_run_id(), "bundled", "", section=self.active_section
                ),
                termination=reason,
            )
        self.running = False
        self.causes_running = False
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.cancel(reason)
        self._notify()

    def close(self) -> None:
        """Окно закрыто: проверка отменяется, а его колбэк больше не зовётся."""
        self.on_changed = None
        self.stop()

    def export(self, path: str | Path) -> bool:
        if self.report is None:
            return False
        try:
            write_report(Path(path), self.report, self.causes)
        except (OSError, ValueError) as error:
            logger.warning("Отчёт не сохранён: %s", type(error).__name__)
            return False
        return True

    # Фоновый поток

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation

    def _post(self, generation: int, apply: Callable[[], None]) -> None:
        with self._lock:
            self._pending.append((generation, apply))
            if self._drain_scheduled:
                return
            self._drain_scheduled = True
        self._loop.dispatch(self._drain)

    def _drain(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
            self._drain_scheduled = False
        changed = False
        for generation, apply in pending:
            if generation == self._generation:
                apply()
                changed = True
        if changed:
            self._notify()

    def _notify(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def _work(self, generation, runner, section, previous) -> None:
        state: dict = {"report": None, "targets": ()}

        def on_main(event) -> None:
            # Остановка могла прийти между запусками: отмена идёт и через первое же событие.
            if not self._is_current(generation):
                runner.cancel()
                return
            if isinstance(event, Started):
                state["targets"] = event.targets
                report = DiagnosticReport(event.context)
                self._post(generation, lambda: self._apply_started(report, event.targets))
            elif isinstance(event, ObservationEvent):
                return  # Следом всегда идёт Updated с полным снимком.
            elif isinstance(event, Updated | Finished):
                state["report"] = event.report
                self._post(generation, lambda: self._apply_report(event.report))

        try:
            runner.run(DiagnosticRequest(section=section), on_main)
            main = state["report"]
            if section is not DiagnosticSection.DNS and main is not None:
                self._run_causes(generation, runner, section, previous, main, state["targets"])
        except Exception as error:
            logger.warning("Проверка сети упала: %s", type(error).__name__, exc_info=True)
            self._post(generation, self._apply_failure)
        self._post(generation, self._apply_finished)

    def _run_causes(self, generation, runner, section, previous, main, targets) -> None:
        if main.termination is not DiagnosticTermination.COMPLETED:
            return
        allowlist = previous.get(DiagnosticSection.ALLOWLIST)
        services = previous.get(DiagnosticSection.SERVICES)
        if section in (None, DiagnosticSection.ALLOWLIST):
            allowlist = main
        if section in (None, DiagnosticSection.SERVICES):
            services = main
        failed = _failed_targets(allowlist, services, targets)
        if not failed:
            return
        self._post(generation, self._apply_causes_started)

        def on_causes(event) -> None:
            if not self._is_current(generation):
                runner.cancel()
            elif isinstance(event, Updated):
                self._post(generation, lambda: self._apply_causes(event.report))
            elif isinstance(event, Finished):
                kept = event.report if same_network(main, event.report) else None
                self._post(generation, lambda: self._apply_causes(kept))

        try:
            runner.run(causes_request(failed), on_causes)
        except Exception as error:
            logger.warning("Разбор причин упал: %s", type(error).__name__, exc_info=True)
            self._post(generation, lambda: self._apply_causes(None))

    # Применение в главном потоке

    def _apply_started(self, report, targets) -> None:
        self.report = report
        self.targets = tuple(targets)

    def _apply_report(self, report) -> None:
        self.report = report

    def _apply_causes_started(self) -> None:
        self.causes_running = True

    def _apply_causes(self, report) -> None:
        self.causes = report

    def _apply_failure(self) -> None:
        self.failed = True
        if self.report is not None:
            self.report = replace(self.report, termination=DiagnosticTermination.INTERNAL_ERROR)

    def _apply_finished(self) -> None:
        self.running = False
        self.causes_running = False
        self._runner = None
