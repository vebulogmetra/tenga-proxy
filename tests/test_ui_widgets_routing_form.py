"""Общий виджет формы маршрутизации (GTK4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


def make_form():
    from gi.repository import Adw

    from src.ui.widgets.routing_form import RoutingForm

    page = Adw.PreferencesPage()
    return RoutingForm(page)


def routing_settings(**kwargs):
    from src.db.config import RoutingSettings

    return RoutingSettings(**kwargs)


def test_load_and_read_round_trip(gtk_ready):
    form = make_form()
    source = routing_settings(
        mode="custom", proxy_list=["a.com"], rule_order=["vpn", "proxy", "direct"], ru_direct=True
    )
    form.load(source)
    target = routing_settings()
    form.read(target)
    assert target.to_dict() == source.to_dict()


def test_lists_sleep_in_proxy_all_and_wake_in_custom(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="proxy_all"))
    assert not form.views["proxy"].get_sensitive()
    assert form.bypass_row.get_sensitive()
    form.select_mode("custom")
    assert form.views["proxy"].get_sensitive()


def test_set_enabled_dims_everything(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom"))
    form.set_enabled(False)
    assert not form.mode_row.get_sensitive()
    assert not form.bypass_row.get_sensitive()
    assert not form.views["proxy"].get_sensitive()
    form.set_enabled(True)
    assert form.mode_row.get_sensitive()
    assert form.views["proxy"].get_sensitive()


def test_bad_entry_raises_and_keeps_the_target(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom", direct_list=["x.com"]))
    form.set_text("direct", "http://user:pw@x.com")
    target = routing_settings(direct_list=["x.com"])
    with pytest.raises(ValueError, match="credentials"):
        form.read(target)
    assert target.direct_list == ["x.com"]


def test_vpn_hint_replaces_the_list_description(gtk_ready):
    from gi.repository import Adw

    from src.ui.widgets.routing_form import RoutingForm

    form = RoutingForm(Adw.PreferencesPage(), vpn_hint="только с VPN")
    assert form.groups[-1].get_description() == "только с VPN"


def test_changed_callback_fires_on_edits(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom"))
    seen = []
    form.connect_changed(lambda: seen.append(1))
    form.set_text("proxy", "a.com")
    form.bypass_row.set_active(not form.bypass_row.get_active())
    assert len(seen) >= 2
