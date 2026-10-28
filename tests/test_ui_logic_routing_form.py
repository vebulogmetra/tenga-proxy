"""Подписи формы маршрутизации (без GTK)."""

from __future__ import annotations

import pytest

from src.core.geo import GeoCatalog
from src.ui.logic.routing_form import (
    LIST_HINT,
    geo_summary,
    normalize_routing_entry,
    ru_direct_subtitle,
)

FULL = GeoCatalog(geosite=frozenset({"category-ru", "category-gov-ru"}), geoip=frozenset({"ru"}))


def test_subtitle_names_the_rules_when_bases_have_them():
    assert ru_direct_subtitle(FULL) == "geosite:category-ru, geosite:category-gov-ru, geoip:ru"


def test_subtitle_warns_when_a_category_is_missing():
    """Тумблер без категории в базе ничего не сделает — пользователь должен это видеть."""
    catalog = GeoCatalog(geosite=frozenset({"category-ru"}), geoip=frozenset())

    assert ru_direct_subtitle(catalog) == (
        "Не сработает полностью: в геобазах нет geosite:category-gov-ru, geoip:ru"
    )


def test_subtitle_without_geo_bases():
    assert ru_direct_subtitle(GeoCatalog()) == "Не сработает: геобазы не найдены"


def test_list_hint_mentions_geo_entries():
    assert "geosite:" in LIST_HINT
    assert "geoip:" in LIST_HINT


def test_geo_summary_counts_categories():
    assert geo_summary(FULL) == "geosite: 2 категорий, geoip: 1"


def test_geo_summary_without_bases():
    assert geo_summary(GeoCatalog()) == "Не найдены: правила geosite: и geoip: не применяются"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("full:Example.COM", "full:example.com"),
        ("domain:Пример.РФ", "domain:xn--e1afmkfd.xn--p1ai"),
        ("full:xn--e1afmkfd.xn--p1ai", "full:xn--e1afmkfd.xn--p1ai"),
        # Регистр регулярного выражения и ключевого слова — часть правила.
        ("regexp:^Api\\.", "regexp:^Api\\."),
        ("keyword:Google", "keyword:Google"),
        ("geosite:category-ru", "geosite:category-ru"),
    ],
)
def test_domain_rules_match_the_name_the_core_compares(raw, expected):
    """Ядро сравнивает правило с именем в нижнем регистре и в punycode."""
    assert normalize_routing_entry(raw) == expected


@pytest.mark.parametrize("raw", ["full:", "full:*.example.com", "domain:bad host"])
def test_malformed_domain_rules_are_rejected(raw):
    with pytest.raises(ValueError, match="Некорректн"):
        normalize_routing_entry(raw)


# --- порядок групп правил (общий для GTK и Qt) ---


def test_order_key_finds_the_preset():
    from src.ui.logic.routing_form import ORDER_LABELS, ORDER_PRESETS, order_key

    assert order_key(["vpn", "proxy", "direct"]) == "vpn_proxy_direct"
    assert set(ORDER_PRESETS) == set(ORDER_LABELS)


def test_unknown_order_falls_back_to_the_first_preset():
    from src.ui.logic.routing_form import order_key

    assert order_key(["proxy"]) == "direct_vpn_proxy"
