"""Подписи формы маршрутизации (без GTK)."""

from __future__ import annotations

from src.core.geo import GeoCatalog
from src.ui.logic.routing_form import LIST_HINT, geo_summary, ru_direct_subtitle

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
