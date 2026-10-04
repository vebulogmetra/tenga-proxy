"""Правила маршрутизации в конфиге сессии."""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.core.geo import GeoCatalog
from src.db.config import LOCAL_NETWORKS, RoutingMode, RoutingSettings
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    rule_values,
    rules_to,
    use_bundled_geo,
    use_custom_lists,
    with_socks_inbound,
    xray_verdict,
)

needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


# --- geo-записи -----------------------------------------------------------


def test_geo_entries_reach_the_right_rule_fields(context, profile):
    """`geoip:` — в ip, `geosite:` — в domain; раньше оба попадали в домены."""
    use_custom_lists(context, direct=["geosite:category-ru", "geoip:ru"])

    config = build_session_config(context, profile)

    assert "geosite:category-ru" in rule_values(config, "direct", "domain")
    assert "geoip:ru" in rule_values(config, "direct", "ip")


def test_unknown_geo_categories_are_dropped(context, profile):
    """Неизвестная категория роняет ядро — запись пропускаем, остальные работают."""
    use_custom_lists(
        context,
        direct=["geosite:category-ru", "geosite:no-such-category", "geoip:zz-nowhere"],
        proxy=["geosite:no-such-either", "blocked.example"],
    )

    config = build_session_config(context, profile)

    everything = str(config["routing"]["rules"])
    assert "no-such" not in everything
    assert "zz-nowhere" not in everything
    assert "geosite:category-ru" in rule_values(config, "direct", "domain")
    assert "domain:blocked.example" in rule_values(config, profile.bean.display_name, "domain")


def test_without_geo_bases_every_geo_entry_is_dropped(context, profile, monkeypatch):
    """Баз рядом с ядром нет (старая установка): geo-правила не должны ронять подключение."""
    monkeypatch.setattr(config_builder, "load_catalog", lambda _dirs: GeoCatalog())
    use_custom_lists(context, direct=["geosite:category-ru", "geoip:ru", "direct.example"])

    config = build_session_config(context, profile)

    assert "geo" not in str(config["routing"]["rules"])
    assert rule_values(config, "direct", "domain") == ["domain:direct.example"]


@needs_xray
def test_core_accepts_lists_with_unknown_geo_categories(context, profile, tmp_path):
    use_custom_lists(
        context,
        direct=["geosite:category-ru", "geosite:no-such-category", "geoip:ru", "geoip:zz-nowhere"],
        proxy=["geosite:google", "*.blocked.example"],
    )

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)


# --- блок-лист ------------------------------------------------------------


def test_block_list_goes_to_blackhole_before_every_other_group(context, profile):
    """Блокировка главнее пользовательских групп при любом их порядке."""
    use_custom_lists(
        context,
        block=["ads.example", "203.0.113.0/24"],
        direct=["direct.example"],
        proxy=["proxy.example"],
    )
    context.config.routing.rule_order = ["proxy", "direct", "vpn"]

    config = build_session_config(context, profile)

    rules = config["routing"]["rules"]
    assert [r["outboundTag"] for r in rules[:2]] == ["block", "block"]
    assert rule_values(config, "block", "domain") == ["domain:ads.example"]
    assert rule_values(config, "block", "ip") == ["203.0.113.0/24"]
    assert {"protocol": "blackhole", "tag": "block"} in config["outbounds"]


def test_blocked_domains_get_nxdomain(context, profile):
    """Соединение по IP режет правило, а имя не резолвится вовсе: `#3` — NXDOMAIN.

    Адрес-заглушка `127.0.0.1` не годится: он попал бы под «локальные сети
    напрямую», и заблокированный запрос ушёл бы мимо блокировки.
    """
    use_custom_lists(context, block=["ads.example", "tracker", "geosite:category-ru", "10.0.0.1"])

    config = build_session_config(context, profile)

    assert config["dns"]["hosts"] == {
        "domain:ads.example": "#3",
        "keyword:tracker": "#3",
        "geosite:category-ru": "#3",
    }


def test_no_block_outbound_without_block_list(context, profile):
    use_custom_lists(context, direct=["direct.example"])

    config = build_session_config(context, profile)

    assert "block" not in {o.get("tag") for o in config["outbounds"]}
    assert "hosts" not in config["dns"]


def test_block_list_is_not_applied_in_proxy_all_mode(context, profile):
    """В режиме «весь трафик через прокси» списки не действуют — и этот тоже."""
    use_custom_lists(context, block=["ads.example"])
    context.config.routing.mode = RoutingMode.PROXY_ALL

    config = build_session_config(context, profile)

    assert not rules_to(config, "block")
    assert "hosts" not in config["dns"]


@needs_xray
def test_core_accepts_block_list(context, profile, tmp_path):
    use_custom_lists(
        context,
        block=["ads.example", "tracker", "full:exact.example", "geosite:category-ru", "10.0.0.1"],
    )

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)


def test_blocked_traffic_is_not_counted_as_proxy_traffic():
    from src.core.xray_manager import XrayManager

    assert "block" in XrayManager._SERVICE_TAGS


# --- готовые правила ------------------------------------------------------


def rule_index(config: dict, key: str, value: str) -> int:
    for index, rule in enumerate(config["routing"]["rules"]):
        if value in rule.get(key, []):
            return index
    raise AssertionError(f"нет правила с {key}={value}")


def test_local_networks_go_direct_by_default():
    assert RoutingSettings().bypass_local_networks is True


def test_local_networks_rule_comes_after_user_lists(context, profile):
    """Готовое правило не должно перебивать явное: подсеть из списка главнее.

    Иначе `10.14.0.0/16` из списка «через VPN» при порядке «напрямую → VPN» ушла
    бы напрямую, совпав с `10.0.0.0/8`.
    """
    use_custom_lists(context, proxy=["10.14.0.0/16"], direct=["direct.example"])
    context.config.routing.bypass_local_networks = True
    context.config.routing.rule_order = ["direct", "vpn", "proxy"]

    config = build_session_config(context, profile)

    assert rule_index(config, "ip", "10.14.0.0/16") < rule_index(config, "ip", "10.0.0.0/8")
    assert set(LOCAL_NETWORKS) <= set(rule_values(config, "direct", "ip"))


def test_local_networks_switch_can_be_turned_off(context, profile):
    use_custom_lists(context, direct=["direct.example"])
    context.config.routing.bypass_local_networks = False

    config = build_session_config(context, profile)

    assert "10.0.0.0/8" not in rule_values(config, "direct", "ip")


def test_russian_sites_go_through_proxy_by_default(context, profile):
    use_custom_lists(context, direct=["direct.example"])

    config = build_session_config(context, profile)

    assert RoutingSettings().ru_direct is False
    assert "geoip:ru" not in str(config["routing"]["rules"])


def test_ru_direct_adds_ip_and_domain_rules(context, profile):
    use_custom_lists(context)
    context.config.routing.ru_direct = True

    config = build_session_config(context, profile)

    assert "geoip:ru" in rule_values(config, "direct", "ip")
    assert rule_values(config, "direct", "domain") == [
        "geosite:category-ru",
        "geosite:category-gov-ru",
    ]


@pytest.mark.parametrize("order", [["direct", "vpn", "proxy"], ["proxy", "direct", "vpn"]])
def test_user_proxy_list_beats_ru_direct(context, profile, order):
    """Российский домен, явно отправленный в прокси, не должен уйти напрямую."""
    use_custom_lists(context, proxy=["blocked.ru.example", "77.88.0.0/16"])
    context.config.routing.ru_direct = True
    context.config.routing.rule_order = order

    config = build_session_config(context, profile)

    ru_rule = rule_index(config, "ip", "geoip:ru")
    assert rule_index(config, "domain", "domain:blocked.ru.example") < ru_rule
    assert rule_index(config, "ip", "77.88.0.0/16") < ru_rule


def test_ru_direct_is_ignored_in_proxy_all_mode(context, profile):
    context.config.routing.mode = RoutingMode.PROXY_ALL
    context.config.routing.ru_direct = True

    config = build_session_config(context, profile)

    assert "geoip:ru" not in str(config["routing"]["rules"])


def test_ru_direct_without_geo_bases_adds_nothing(context, profile, monkeypatch):
    """Старая установка без геобаз: тумблер не должен ронять подключение."""
    monkeypatch.setattr(config_builder, "load_catalog", lambda _dirs: GeoCatalog())
    use_custom_lists(context)
    context.config.routing.ru_direct = True

    config = build_session_config(context, profile)

    assert "geo" not in str(config)


@needs_xray
def test_core_accepts_ready_made_rules(context, profile, tmp_path):
    use_custom_lists(context, proxy=["blocked.ru.example"], direct=["direct.example"])
    context.config.routing.ru_direct = True
    context.config.routing.bypass_local_networks = True

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
