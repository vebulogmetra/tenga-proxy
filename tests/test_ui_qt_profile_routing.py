"""Qt-окно «VPN и маршруты» профиля."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.fmt import parse_link
from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog
from tests.support.qt import wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#P"


def _profile(vpn=None, routing=None):
    return SimpleNamespace(
        id=1,
        bean=parse_link(LINK),
        vpn_settings=vpn if vpn is not None else VpnSettings(),
        routing_settings=routing if routing is not None else RoutingSettings(),
    )


def test_fields_are_loaded(qapp):
    profile = _profile(
        vpn=VpnSettings(enabled=True, connection_name="work"),
        routing=RoutingSettings(mode=RoutingMode.CUSTOM, proxy_list=["a.com", "b.com"]),
    )

    dialog = ProfileRoutingDialog(profile)

    assert dialog.name_edit.text() == "P"
    assert dialog.address_label.text() == "host.example:443"
    assert dialog.vpn_check.isChecked() and dialog.vpn_name_edit.text() == "work"
    assert dialog.lists["proxy"].toPlainText() == "a.com\nb.com"
    assert dialog.mode_combo.selected() == RoutingMode.CUSTOM


def test_vpn_fields_follow_the_switch(qapp):
    dialog = ProfileRoutingDialog(_profile())
    assert not dialog.vpn_name_edit.isEnabled()

    dialog.vpn_check.setChecked(True)

    assert dialog.vpn_name_edit.isEnabled()


def test_lists_sleep_in_proxy_all(qapp):
    dialog = ProfileRoutingDialog(_profile())

    dialog.mode_combo.select(RoutingMode.PROXY_ALL)
    assert not dialog.lists["proxy"].isEnabled()
    assert dialog.bypass_check.isEnabled()
    dialog.mode_combo.select(RoutingMode.CUSTOM)
    assert dialog.lists["proxy"].isEnabled()


def test_save_writes_everything(qapp):
    profile = _profile()
    dialog = ProfileRoutingDialog(profile)
    saved = []
    dialog.routing_saved.connect(lambda: saved.append(1))
    dialog.vpn_check.setChecked(True)
    dialog.vpn_name_edit.setText("work")
    dialog.mode_combo.select(RoutingMode.CUSTOM)
    dialog.order_combo.select("vpn_proxy_direct")
    dialog.lists["proxy"].setPlainText("a.com\n\n b.com , a.com \n")
    dialog.lists["block"].setPlainText("ads.example")

    assert dialog.save()

    assert saved
    assert profile.vpn_settings.enabled and profile.vpn_settings.connection_name == "work"
    assert profile.routing_settings.proxy_list == ["a.com", "b.com"]
    assert profile.routing_settings.block_list == ["ads.example"]
    assert profile.routing_settings.rule_order == ["vpn", "proxy", "direct"]


def test_bad_entry_marks_its_list_and_keeps_the_profile(qapp):
    profile = _profile(routing=RoutingSettings(mode=RoutingMode.CUSTOM, direct_list=["x.com"]))
    dialog = ProfileRoutingDialog(profile)
    dialog.lists["direct"].setPlainText("http://user:pw@x.com")

    assert not dialog.save()

    assert dialog.lists["direct"].property("error") is True
    assert not dialog.status.isHidden()
    assert profile.routing_settings.direct_list == ["x.com"]


def test_blank_vpn_name_keeps_the_previous_one(qapp):
    profile = _profile(vpn=VpnSettings(enabled=True, connection_name="old"))
    dialog = ProfileRoutingDialog(profile)
    dialog.vpn_name_edit.setText("  ")

    dialog.save()

    assert profile.vpn_settings.connection_name == "old"


def test_unknown_order_falls_back_to_the_first(qapp):
    dialog = ProfileRoutingDialog(_profile(routing=RoutingSettings(rule_order=["nonsense"])))

    assert dialog.order_combo.currentIndex() == 0


def test_edits_autosave_and_closing_flushes(qapp):
    profile = _profile()
    dialog = ProfileRoutingDialog(profile)
    saved = []
    dialog.routing_saved.connect(lambda: saved.append(1))

    dialog.name_edit.setText("Новое")
    assert dialog.autosave.pending
    dialog.reject()

    assert saved == [1]
    assert profile.bean.name == "Новое"

    dialog = ProfileRoutingDialog(profile)
    dialog.routing_saved.connect(lambda: saved.append(2))
    dialog.bypass_check.toggle()
    wait_until(lambda: 2 in saved, timeout=2)
