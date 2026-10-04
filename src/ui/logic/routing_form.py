"""Подписи формы маршрутизации. GTK не импортируется."""

from __future__ import annotations

from src.core.config import find_xray_binary
from src.core.geo import RU_DIRECT_GEOIP, RU_DIRECT_GEOSITES, GeoCatalog, asset_dirs, load_catalog

LIST_HINT = "По одной записи в строке: домен, подсеть, geosite:категория, geoip:страна"
BLOCK_HINT = "Соединения обрываются, имена не резолвятся. Применяется раньше остальных списков"

_RU_DIRECT_RULES = (*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP)


def current_catalog() -> GeoCatalog:
    """Каталог тех геобаз, которые увидит ядро."""
    return load_catalog(asset_dirs(find_xray_binary()))


def ru_direct_subtitle(catalog: GeoCatalog) -> str:
    """Что сделает тумблер «российские сайты и IP напрямую» с этими геобазами."""
    missing = [rule for rule in _RU_DIRECT_RULES if not catalog.knows(rule)]
    if not missing:
        return ", ".join(_RU_DIRECT_RULES)
    if len(missing) == len(_RU_DIRECT_RULES):
        return "Не сработает: геобазы не найдены"
    return "Не сработает полностью: в геобазах нет " + ", ".join(missing)
