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
    PROFILE,
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
    assert group.text() == "Подписка"
    assert group.rowCount() == 2
    assert model.item(0, PING_COLUMN).text() == "2"
    assert group.child(1, 0).text() == "Без флага"
    assert group.child(1, PING_COLUMN).text() == "—"
    assert group.child(0, TYPE_COLUMN).text() == "VLESS"


def test_flag_prefix_turns_into_an_icon(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    berlin = model.item(0, 0).child(0, 0)

    assert berlin.text() == "Берлин"
    assert not berlin.icon().isNull()
    assert berlin.toolTip() == "🇩🇪 Берлин"


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
    assert model.item(0, PING_COLUMN).text() == "0 / 2"

    progress.record(5)
    model.update_group_progress(1, progress)

    assert model.item(0, PING_COLUMN).text() == "1 / 2"


def test_rebuild_drops_old_rows(qapp):
    model = ProfileTreeModel()
    model.set_rows(_rows())

    model.set_rows([])

    assert model.rowCount() == 0
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Имя"
