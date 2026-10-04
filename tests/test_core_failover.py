"""Автопереключение на другой профиль группы, когда сервер перестал отвечать."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.failover import RECENT_FAILURE_TTL_SECONDS, FailoverController, pick_candidate
from src.core.monitor import ConnectionStatus

SILENT = ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=True)
ALIVE = ConnectionStatus(proxy_ok=True, server_probed=True)


def profile(profile_id: int, latency_ms: int = -1, group_id: int = 1):
    return SimpleNamespace(
        id=profile_id, group_id=group_id, latency_ms=latency_ms, name=f"P{profile_id}"
    )


# --- выбор кандидата ---


def test_candidate_with_the_lowest_known_latency_wins():
    profiles = [profile(1, 50), profile(2, 300), profile(3, 120), profile(4, -1)]

    assert pick_candidate(profiles, excluded={1}).id == 3


def test_unmeasured_profiles_come_after_measured_ones_in_list_order():
    profiles = [profile(1, 50), profile(2, -1), profile(3, -1), profile(4, 900)]

    assert pick_candidate(profiles, excluded={1}).id == 4
    assert pick_candidate(profiles, excluded={1, 4}).id == 2


def test_no_candidate_when_everything_is_excluded():
    profiles = [profile(1, 50), profile(2, 80)]

    assert pick_candidate(profiles, excluded={1, 2}) is None
    assert pick_candidate([], excluded=set()) is None


# --- решение «переключать или нет» ---


class Harness:
    """Контроллер с подменённым окружением: профили, время, сеть, действия."""

    def __init__(self, profiles, *, enabled=True, threshold=3, current=1):
        self.profiles = {item.id: item for item in profiles}
        self.switched: list[int] = []
        self.messages: list[str] = []
        self.clock = 1000.0
        self.online = True
        self.state = SimpleNamespace(is_running=True, started_profile_id=current)
        self.monitoring = SimpleNamespace(failover_enabled=enabled, failover_threshold=threshold)
        context = SimpleNamespace(
            proxy_state=self.state,
            config=SimpleNamespace(monitoring=self.monitoring),
            profiles=SimpleNamespace(
                get_profile=self.profiles.get,
                get_profiles_in_group=lambda group_id: [
                    item for item in self.profiles.values() if item.group_id == group_id
                ],
            ),
        )
        self.controller = FailoverController(
            context,
            switch_to=self._switch,
            notify=self.messages.append,
            network_available=lambda: self.online,
            now=lambda: self.clock,
        )

    def _switch(self, profile_id: int) -> None:
        self.switched.append(profile_id)
        self.state.started_profile_id = profile_id

    def feed(self, *statuses: ConnectionStatus) -> None:
        for status in statuses:
            self.controller.handle_status(status, status)


def test_switches_after_the_threshold_of_consecutive_failures():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT)
    assert harness.switched == []

    harness.feed(SILENT)
    assert harness.switched == [2]


def test_switch_is_announced_with_both_profile_names():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)

    assert len(harness.messages) == 1
    assert "P1" in harness.messages[0]
    assert "P2" in harness.messages[0]


def test_a_successful_check_resets_the_counter():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, ALIVE, SILENT, SILENT)

    assert harness.switched == []


def test_nothing_happens_while_failover_is_disabled():
    harness = Harness([profile(1, 50), profile(2, 80)], enabled=False)

    harness.feed(SILENT, SILENT, SILENT, SILENT)

    assert harness.switched == []
    assert harness.messages == []


def test_statuses_without_a_fresh_server_probe_are_not_counted():
    """Ручная проверка повторяет прошлый вердикт: считать её — значит считать дважды."""
    harness = Harness([profile(1, 50), profile(2, 80)])
    stale = ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=False)

    harness.feed(stale, stale, stale, stale)

    assert harness.switched == []


def test_failures_without_network_are_not_blamed_on_the_server():
    harness = Harness([profile(1, 50), profile(2, 80)])
    harness.online = False

    harness.feed(SILENT, SILENT, SILENT, SILENT)

    assert harness.switched == []


def test_candidates_come_only_from_the_group_of_the_active_profile():
    harness = Harness([profile(1, 50), profile(2, 10, group_id=2), profile(3, 400)])

    harness.feed(SILENT, SILENT, SILENT)

    assert harness.switched == [3]


def test_recently_failed_profiles_are_skipped():
    harness = Harness([profile(1, 50), profile(2, 80), profile(3, 200)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.feed(SILENT, SILENT, SILENT)  # 2 → 3, а не обратно на 1

    assert harness.switched == [2, 3]


def test_failed_profile_becomes_a_candidate_again_after_the_ttl():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.clock += RECENT_FAILURE_TTL_SECONDS + 1
    harness.feed(SILENT, SILENT, SILENT)  # 2 → 1

    assert harness.switched == [2, 1]


def test_exhausted_group_is_reported_once_and_the_connection_is_kept():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.feed(SILENT, SILENT, SILENT)  # кандидатов нет
    harness.feed(SILENT, SILENT, SILENT)  # и снова нет — без повторного сообщения

    assert harness.switched == [2]
    assert len(harness.messages) == 2
    assert "нет" in harness.messages[1]
    assert harness.state.is_running is True


def test_manual_switch_to_another_profile_restarts_the_count():
    harness = Harness([profile(1, 50), profile(2, 80), profile(3, 90)])

    harness.feed(SILENT, SILENT)
    harness.state.started_profile_id = 3  # пользователь подключился сам
    harness.feed(SILENT, SILENT)

    assert harness.switched == []


def test_stopped_proxy_resets_the_count():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT)
    harness.state.is_running = False
    harness.feed(SILENT)
    harness.state.is_running = True
    harness.feed(SILENT, SILENT)

    assert harness.switched == []
