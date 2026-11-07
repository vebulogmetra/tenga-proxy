"""Общий виджет формы маршрутизации (Qt)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from src.db.config import RoutingMode, RoutingSettings
from src.ui.qt.widgets.routing_form import RoutingForm

pytestmark = pytest.mark.qt


def test_load_and_read_round_trip(qapp):
    form = RoutingForm()
    source = RoutingSettings(
        mode=RoutingMode.CUSTOM,
        proxy_list=["a.com"],
        rule_order=["vpn", "proxy", "direct"],
        ru_direct=True,
    )
    form.load(source)
    target = RoutingSettings()
    form.read(target)
    assert target.to_dict() == source.to_dict()


def test_lists_sleep_in_proxy_all(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.PROXY_ALL))
    assert not form.lists["proxy"].isEnabled()
    assert form.bypass_check.isEnabled()
    form.mode_combo.select(RoutingMode.CUSTOM)
    assert form.lists["proxy"].isEnabled()


def test_set_enabled_dims_everything(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.CUSTOM))
    form.set_enabled(False)
    assert not form.mode_combo.isEnabled()
    assert not form.bypass_check.isEnabled()
    assert not form.lists["proxy"].isEnabled()
    form.set_enabled(True)
    assert form.lists["proxy"].isEnabled()


def test_vpn_hint_replaces_the_placeholder(qapp):
    form = RoutingForm(vpn_hint="только с VPN")
    assert form.lists["vpn"].placeholderText() == "только с VPN"


def test_bad_entry_marks_its_list_and_raises(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.CUSTOM))
    form.lists["direct"].setPlainText("http://user:pw@x.com")
    target = RoutingSettings(direct_list=["x.com"])
    with pytest.raises(ValueError, match="credentials"):
        form.read(target)
    assert form.lists["direct"].property("error") is True
    assert target.direct_list == ["x.com"]
    form.lists["direct"].setPlainText("ok.com")
    form.read(target)
    assert form.lists["direct"].property("error") is False


def test_fields_cover_every_control(qapp):
    form = RoutingForm()
    fields = form.fields()
    assert form.mode_combo in fields and form.order_combo in fields
    assert form.bypass_check in fields and form.ru_direct_check in fields
    assert all(edit in fields for edit in form.lists.values())
