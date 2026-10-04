"""Проверка обновлений ядра: сравнение версий и разбор релизов GitHub."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.core_update import (
    AVAILABLE,
    BEHIND_PINNED,
    CHECK_INTERVAL_SECONDS,
    CURRENT,
    PINNED_CORE_VERSION,
    RELEASES_URL,
    UNKNOWN,
    KnownReleases,
    evaluate,
    fetch_releases,
    is_check_due,
    known_releases,
    newest_releases,
    parse_version,
    refresh_known_releases,
)
from src.db.data_store import DataStore

INSTALL_SCRIPT = Path("core/scripts/install_dev.sh")

# Срез настоящего ответа GitHub от 2026-10-03: только нужные поля.
PAYLOAD = [
    {"tag_name": "v26.9.30", "prerelease": True, "draft": False},
    {"tag_name": "v26.9.9", "prerelease": True, "draft": False},
    {"tag_name": "v26.7.28", "prerelease": True, "draft": False},
    {"tag_name": "v26.3.27", "prerelease": False, "draft": False},
    {"tag_name": "v26.2.6", "prerelease": False, "draft": False},
]
KNOWN = KnownReleases(stable="26.3.27", prerelease="26.9.30")


# --- версии ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("26.9.9", (26, 9, 9)),
        ("v26.9.30", (26, 9, 30)),
        ("Xray 26.3.27 (Xray, Penetrates Everything.) 52a412d (go1.27.1 linux/amd64)", (26, 3, 27)),
        ("1.8", (1, 8)),
        ("", None),
        ("—", None),
        ("unknown", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_versions_compare_by_numbers_not_by_text():
    assert parse_version("26.9.30") > parse_version("26.9.9")
    assert parse_version("26.10.1") > parse_version("26.9.30")


@pytest.mark.skipif(not INSTALL_SCRIPT.exists(), reason="скрипта установки нет в этой копии")
def test_pinned_version_matches_the_install_script():
    """Версия закреплена в двух местах: в скрипте установки и здесь."""
    match = re.search(r'^\s*XRAY_VERSION="([^"]+)"', INSTALL_SCRIPT.read_text(), re.MULTILINE)

    assert match is not None, "в install_dev.sh нет XRAY_VERSION — этап 1 не выполнен"
    assert match.group(1) == PINNED_CORE_VERSION


# --- релизы GitHub ---


def test_newest_releases_picks_the_newest_stable_and_the_newest_prerelease():
    assert newest_releases(PAYLOAD) == KNOWN


def test_newest_releases_ignores_drafts_and_garbage():
    payload = [
        {"tag_name": "v99.1.1", "prerelease": False, "draft": True},
        {"tag_name": "nightly", "prerelease": True, "draft": False},
        {"prerelease": False},
        "строка вместо объекта",
        {"tag_name": "v26.3.27", "prerelease": False, "draft": False},
    ]

    assert newest_releases(payload) == KnownReleases(stable="26.3.27", prerelease="")


def test_newest_releases_survives_an_unexpected_answer():
    assert newest_releases({"message": "API rate limit exceeded"}) == KnownReleases()


def test_fetch_asks_github_without_any_user_data():
    seen: dict = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return PAYLOAD

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    assert fetch_releases(get=fake_get) == KNOWN
    assert seen["url"] == RELEASES_URL
    assert seen["headers"] == {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tenga-proxy",
    }
    assert seen["timeout"] > 0
    assert set(seen) == {"url", "headers", "timeout"}


# --- что сказать пользователю ---


def test_prerelease_is_offered_when_a_prerelease_is_installed():
    status = evaluate("26.9.9", KNOWN, pinned="26.9.9")

    assert status.kind == AVAILABLE
    assert status.target == "26.9.30"


def test_prerelease_is_not_offered_to_a_stable_core():
    status = evaluate("26.3.27", KNOWN, pinned="26.3.27")

    assert status.kind == CURRENT


def test_stable_update_is_offered_to_a_stable_core():
    status = evaluate("26.2.6", KNOWN, pinned="26.2.6")

    assert status.kind == AVAILABLE
    assert status.target == "26.3.27"


def test_newest_prerelease_installed_is_current():
    assert evaluate("26.9.30", KNOWN, pinned="26.9.9").kind == CURRENT


def test_core_older_than_the_pinned_version_is_reported_first():
    status = evaluate("26.3.27", KNOWN, pinned="26.9.9")

    assert status.kind == BEHIND_PINNED
    assert status.target == "26.9.9"


def test_nothing_is_claimed_before_the_first_check():
    assert evaluate("26.9.9", KnownReleases(), pinned="26.9.9").kind == UNKNOWN


def test_unreadable_installed_version_is_unknown():
    assert evaluate("—", KNOWN).kind == UNKNOWN


# --- расписание и хранение ---


def test_check_is_due_on_first_run_and_after_the_interval():
    config = DataStore()
    assert is_check_due(config, now=1_000_000) is True

    config.core_update_checked_at = 1_000_000
    assert is_check_due(config, now=1_000_000 + CHECK_INTERVAL_SECONDS - 1) is False
    assert is_check_due(config, now=1_000_000 + CHECK_INTERVAL_SECONDS) is True


def test_refresh_stores_what_github_said_and_when():
    config = DataStore()

    result = refresh_known_releases(config, now=1_700_000_000.9, fetch=lambda: KNOWN)

    assert result == KNOWN
    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1_700_000_000
    assert known_releases(DataStore.from_dict(config.to_dict())) == KNOWN


def test_failed_refresh_keeps_the_previous_knowledge_and_stays_due():
    config = DataStore()
    refresh_known_releases(config, now=1000, fetch=lambda: KNOWN)

    def offline():
        raise OSError("нет сети")

    with pytest.raises(OSError, match="нет сети"):
        refresh_known_releases(config, now=1000 + CHECK_INTERVAL_SECONDS, fetch=offline)

    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1000


def test_empty_answer_does_not_erase_the_previous_knowledge():
    config = DataStore()
    refresh_known_releases(config, now=1000, fetch=lambda: KNOWN)

    refresh_known_releases(config, now=2000, fetch=KnownReleases)

    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1000
