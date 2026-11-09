"""Модель дерева серверов Qt над строками profiles_view."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from src.ui.logic.latency import PingProgress
from src.ui.logic.profiles_view import GroupRow, ProfileRow
from src.ui.qt.models import (
    GROUP,
    PING_COLUMN,
    PROBE_FAILED_ROLE,
    PROFILE,
    PROGRESS_ROLE,
    TYPE_COLUMN,
    ProfileTreeModel,
)

pytestmark = pytest.mark.qt


def _rows():
    return [
        GroupRow(
            group_id=1,
            title="Подписка",
            icon_name="",
            is_subscription=True,
            children=(
                ProfileRow(5, "🇩🇪 Берлин", "vless", "de.example:443", 40, True),
                ProfileRow(6, "Без флага", "trojan", "x.example:443", -1, False),
            ),
        ),
    ]


def test_groups_hold_their_profiles(qapp):
    model = ProfileTreeModel()

    model.set_rows(_rows())

    group = model.item(0, 0)
    assert group.text() == "Подписка  ·  Серверов: 2"
    assert group.rowCount() == 2
    assert model.item(0, PING_COLUMN).text() == ""
    assert group.child(1, 0).text() == "Без флага"
    assert group.child(1, PING_COLUMN).text() == "—"
    assert group.child(0, TYPE_COLUMN).text() == "VLESS"


def test_flag_prefix_turns_into_an_icon(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    berlin = model.item(0, 0).child(0, 0)

    assert berlin.text() == "Берлин  ·  Подключён"
    assert not berlin.icon().isNull()
    assert berlin.toolTip().splitlines() == ["🇩🇪 Берлин", "VLESS · de.example:443"]


def test_active_profile_is_bold(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())
    group = model.item(0, 0)

    assert group.child(0, 0).font().bold()
    assert not group.child(1, 0).font().bold()


def test_targets_name_the_row(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    assert model.target(model.group_index(1)) == (GROUP, 1)
    assert model.target(model.profile_index(6)) == (PROFILE, 6)
    assert model.target(model.profile_index(99)) is None


def test_group_progress_replaces_the_count(qapp):
    model = ProfileTreeModel()
    progress = PingProgress({1: [5, 6]})
    model.set_rows(_rows(), progress)
    assert "Проверено: 0 / 2" in model.item(0, 0).text()
    assert model.item(0, 0).data(PROGRESS_ROLE) == (0, 2)

    progress.record(5)
    model.update_group_progress(1, progress)

    assert "Проверено: 1 / 2" in model.item(0, 0).text()
    assert model.item(0, 0).data(PROGRESS_ROLE) == (1, 2)
    assert model.item(0, PING_COLUMN).text() == ""
    model.update_group_progress(1, None)
    assert model.item(0, 0).data(PROGRESS_ROLE) is None


def test_rebuild_drops_old_rows(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    model.set_rows([])

    assert model.rowCount() == 0
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Имя"


def test_group_progress_keeps_subscription_details(qapp):
    model = ProfileTreeModel()
    progress = PingProgress({1: [5, 6]})
    model.set_rows(_rows(), progress, {1: ("1 GB из 2 GB", False)})
    progress.record(5)
    model.update_group_progress(1, progress)
    assert "1 GB из 2 GB" in model.item(0, 0).text()
    assert "Проверено: 1 / 2" in model.item(0, 0).text()


def test_failed_probe_has_a_label_tooltip_and_error_flag(qapp):
    from src.core.probe_result import ProbeFailure
    from src.ui.logic.appearance import ERROR_TEXT

    failed = ProfileRow(
        7,
        "Мёртвый",
        "vless",
        "d.example:443",
        -1,
        False,
        probe_failure=ProbeFailure.TIMEOUT,
        probe_detail="ReadTimeout",
    )
    model = ProfileTreeModel()
    model.set_rows([GroupRow(1, "Группа", "", False, (failed, *_rows()[0].children))])

    group = model.item(0, 0)
    ping = group.child(0, PING_COLUMN)
    assert ping.text() == "нет ответа"
    assert ping.toolTip() == "Сервер не ответил за 3 с\nReadTimeout"
    assert ping.data(PROBE_FAILED_ROLE) is True
    assert ping.foreground().color().name() == ERROR_TEXT

    measured = group.child(1, PING_COLUMN)
    assert measured.text() == "40 мс"
    assert measured.toolTip() == ""
    assert measured.data(PROBE_FAILED_ROLE) is False
