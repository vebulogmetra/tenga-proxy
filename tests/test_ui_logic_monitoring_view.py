"""Tests for the monitoring summary logic (no GTK needed)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import pytest

from src.ui.logic.monitoring_view import (
    NOT_SET,
    UNKNOWN,
    monitoring_view,
    routing_rows,
)


@dataclass
class FakeStatus:
    proxy_ok: bool = False
    vpn_ok: bool = True
    last_check_time: float = 0.0
    proxy_error: str = ""
    vpn_error: str = ""


@dataclass
class FakeRouting:
    mode: str = "custom"
    proxy_list: list[str] = field(default_factory=list)
    direct_list: list[str] = field(default_factory=list)
    vpn_list: list[str] = field(default_factory=list)
    bypass_local_networks: bool = False


def values(rows):
    return {row.title: row.value for row in rows}


def test_disconnected_shows_dashes():
    view = monitoring_view(FakeStatus(), FakeRouting(), is_running=False)
    assert all(row.value == UNKNOWN for row in view.routing)


def test_missing_profile_is_reported():
    view = monitoring_view(
        FakeStatus(proxy_ok=True), FakeRouting(), is_running=True, profile_found=False
    )
    assert values(view.routing)["Режим"] == "Профиль не найден"


def test_proxy_all_with_bypass():
    rows = routing_rows(FakeRouting(mode="proxy_all", bypass_local_networks=True))
    result = values(rows)
    assert result["Режим"] == "PROXY_ALL"
    assert result["DIRECT"] == "активен (bypass local)"
    assert result["PROXY"] == "активен (весь трафик)"
    assert result["VPN"] == NOT_SET


def test_proxy_all_without_bypass():
    rows = routing_rows(FakeRouting(mode="proxy_all", bypass_local_networks=False))
    assert values(rows)["DIRECT"] == NOT_SET


def test_custom_counts_rules():
    routing = FakeRouting(
        mode="custom",
        direct_list=["a", "b"],
        proxy_list=["c"],
        bypass_local_networks=True,
    )
    result = values(routing_rows(routing))
    assert result["Режим"] == "CUSTOM"
    # Обход локальных сетей — ещё одно правило сверх списка.
    assert result["DIRECT"] == "активен (3 правил)"
    assert result["PROXY"] == "активен (1 правил + default)"


def test_custom_without_proxy_rules_falls_back_to_default():
    result = values(routing_rows(FakeRouting(mode="custom")))
    assert result["PROXY"] == "активен (default)"
    assert result["DIRECT"] == NOT_SET


def test_vpn_not_set_without_rules():
    result = values(routing_rows(FakeRouting(mode="custom"), vpn_enabled=True, vpn_is_up=True))
    assert result["VPN"] == NOT_SET


def test_vpn_active():
    routing = FakeRouting(mode="custom", vpn_list=["x", "y"])
    result = values(routing_rows(routing, vpn_enabled=True, vpn_is_up=True))
    assert result["VPN"] == "активен (2 правил)"


def test_vpn_rules_present_but_link_is_down():
    routing = FakeRouting(mode="custom", vpn_list=["x"])
    result = values(routing_rows(routing, vpn_enabled=True, vpn_is_up=False))
    assert result["VPN"] == "правила есть (1), VPN не активен"


def test_vpn_rules_present_but_disabled():
    routing = FakeRouting(mode="custom", vpn_list=["x"])
    result = values(routing_rows(routing, vpn_enabled=False, vpn_is_up=False))
    assert result["VPN"] == "правила есть (1), VPN выключен"


def test_last_check_never():
    view = monitoring_view(FakeStatus(), FakeRouting(), is_running=False)
    assert view.last_check == UNKNOWN


def test_last_check_formats_the_timestamp():
    timestamp = 1_700_000_000.0
    view = monitoring_view(
        FakeStatus(last_check_time=timestamp), FakeRouting(), is_running=False
    )
    expected = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
    assert view.last_check == expected


def test_proxy_error_carries_the_error_class():
    status = FakeStatus(proxy_ok=False, proxy_error="Процесс xray-core не запущен")
    view = monitoring_view(status, FakeRouting(), is_running=True)
    proxy_row = next(row for row in view.connection if row.title == "Прокси")
    assert proxy_row.value == "Процесс xray-core не запущен"
    assert proxy_row.css_class == "status-error"


def test_proxy_ok_carries_the_connected_class():
    view = monitoring_view(FakeStatus(proxy_ok=True), FakeRouting(), is_running=True)
    proxy_row = next(row for row in view.connection if row.title == "Прокси")
    assert proxy_row.css_class == "status-connected"


@pytest.mark.parametrize("mode", ["proxy_all", "custom"])
def test_routing_always_returns_four_rows(mode):
    assert len(routing_rows(FakeRouting(mode=mode))) == 4
