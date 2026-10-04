"""Правила маршрутизации в конфиге сессии."""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.core.geo import GeoCatalog
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    rule_values,
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
