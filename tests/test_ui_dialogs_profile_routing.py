"""Widget tests for the GTK4 profile VPN and routing dialog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.gtk

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#P"


def make_profile(vpn=None, routing=None):
    from src.db.config import RoutingSettings, VpnSettings
    from src.fmt import parse_link

    return SimpleNamespace(
        id=1,
        bean=parse_link(LINK),
        vpn_settings=vpn if vpn is not None else VpnSettings(),
        routing_settings=routing if routing is not None else RoutingSettings(),
    )


def make_dialog(profile):
    from src.ui.dialogs4.profile_routing import ProfileRoutingDialog

    return ProfileRoutingDialog(profile)


def vpn_settings(**kwargs):
    from src.db.config import VpnSettings

    return VpnSettings(**kwargs)


def routing_settings(**kwargs):
    from src.db.config import RoutingSettings

    return RoutingSettings(**kwargs)


def test_vpn_fields_are_loaded(gtk_ready):
    vpn = vpn_settings(enabled=True, connection_name="work", auto_connect=True)
    dialog = make_dialog(make_profile(vpn=vpn))
    assert dialog.vpn_row.get_active()
    assert dialog.vpn_name_row.get_text() == "work"
    assert dialog.vpn_auto_row.get_active()


def test_vpn_rows_are_insensitive_while_disabled(gtk_ready):
    dialog = make_dialog(make_profile())
    assert not dialog.vpn_name_row.get_sensitive()
    assert not dialog.vpn_auto_row.get_sensitive()


def test_enabling_vpn_wakes_its_rows(gtk_ready):
    dialog = make_dialog(make_profile())
    dialog.vpn_row.set_active(True)
    assert dialog.vpn_name_row.get_sensitive()


def test_a_missing_vpn_section_falls_back_to_defaults(gtk_ready):
    """Старый профиль мог быть сохранён без секции VPN."""
    profile = make_profile()
    profile.vpn_settings = None
    dialog = make_dialog(profile)
    assert not dialog.vpn_row.get_active()


def test_routing_lists_are_loaded(gtk_ready):
    routing = routing_settings(mode="custom", proxy_list=["a.com", "b.com"])
    dialog = make_dialog(make_profile(routing=routing))
    assert dialog.proxy_text() == "a.com\nb.com"


def test_the_routing_mode_is_preselected(gtk_ready):
    routing = routing_settings(mode="proxy_all")
    assert make_dialog(make_profile(routing=routing)).selected_mode() == "proxy_all"


def test_routing_lists_are_insensitive_in_proxy_all(gtk_ready):
    """В режиме «весь трафик» списки ни на что не влияют."""
    routing = routing_settings(mode="proxy_all")
    dialog = make_dialog(make_profile(routing=routing))
    assert not dialog.proxy_view.get_sensitive()


def test_switching_to_custom_wakes_the_lists(gtk_ready):
    routing = routing_settings(mode="proxy_all")
    dialog = make_dialog(make_profile(routing=routing))
    dialog.select_mode("custom")
    assert dialog.proxy_view.get_sensitive()


def test_saving_writes_the_vpn_settings(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.vpn_row.set_active(True)
    dialog.vpn_name_row.set_text("work")
    dialog.vpn_auto_row.set_active(True)
    dialog.save()
    assert profile.vpn_settings.enabled
    assert profile.vpn_settings.connection_name == "work"
    assert profile.vpn_settings.auto_connect


def test_saving_parses_the_routing_lists(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.select_mode("custom")
    dialog.set_proxy_text("a.com\n\n b.com , a.com \n")
    dialog.save()
    assert profile.routing_settings.proxy_list == ["a.com", "b.com"]


def test_saving_writes_the_mode(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.select_mode("proxy_all")
    dialog.save()
    assert profile.routing_settings.mode == "proxy_all"


def test_the_bypass_switch_round_trips(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.bypass_row.set_active(True)
    dialog.save()
    assert profile.routing_settings.bypass_local_networks


def test_the_rule_order_round_trips(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.select_order(["vpn", "direct", "proxy"])
    dialog.save()
    assert profile.routing_settings.rule_order == ["vpn", "direct", "proxy"]


def test_the_rule_order_is_preselected(gtk_ready):
    routing = routing_settings(rule_order=["proxy", "vpn", "direct"])
    dialog = make_dialog(make_profile(routing=routing))
    assert dialog.selected_order() == ["proxy", "vpn", "direct"]


def test_an_unknown_rule_order_falls_back_to_the_first(gtk_ready):
    routing = routing_settings(rule_order=["nonsense"])
    assert make_dialog(make_profile(routing=routing)).order_row.get_selected() == 0


def test_a_blank_vpn_name_keeps_the_previous_one(gtk_ready):
    """Пустое имя подключения сделало бы автоподключение бессмысленным."""
    profile = make_profile(vpn=vpn_settings(enabled=True, connection_name="work"))
    dialog = make_dialog(profile)
    dialog.vpn_name_row.set_text("   ")
    dialog.save()
    assert profile.vpn_settings.connection_name == "work"


def test_the_profile_name_round_trips(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.name_row.set_text("Renamed")
    dialog.save()
    assert profile.bean.name == "Renamed"


def test_all_three_lists_are_saved(gtk_ready):
    profile = make_profile()
    dialog = make_dialog(profile)
    dialog.select_mode("custom")
    dialog.set_proxy_text("p.com")
    dialog.set_direct_text("d.com")
    dialog.set_vpn_text("v.com")
    dialog.save()
    assert profile.routing_settings.proxy_list == ["p.com"]
    assert profile.routing_settings.direct_list == ["d.com"]
    assert profile.routing_settings.vpn_list == ["v.com"]
