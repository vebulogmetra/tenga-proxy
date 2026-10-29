"""Подписи формы маршрутизации. GTK не импортируется."""

from __future__ import annotations

from src.core.config import find_xray_binary
from src.core.geo import RU_DIRECT_GEOIP, RU_DIRECT_GEOSITES, GeoCatalog, asset_dirs, load_catalog

LIST_HINT = "По одной записи в строке: домен, подсеть, geosite:категория, geoip:страна"
BLOCK_HINT = "Соединения обрываются, имена не резолвятся. Применяется раньше остальных списков"

# Порядок групп правил маршрутизации профиля: ключ настройки → порядок.
ORDER_PRESETS: dict[str, list[str]] = {
    "direct_vpn_proxy": ["direct", "vpn", "proxy"],
    "direct_proxy_vpn": ["direct", "proxy", "vpn"],
    "vpn_direct_proxy": ["vpn", "direct", "proxy"],
    "vpn_proxy_direct": ["vpn", "proxy", "direct"],
    "proxy_direct_vpn": ["proxy", "direct", "vpn"],
    "proxy_vpn_direct": ["proxy", "vpn", "direct"],
}

ORDER_LABELS = {
    "direct_vpn_proxy": "Напрямую → VPN → Прокси",
    "direct_proxy_vpn": "Напрямую → Прокси → VPN",
    "vpn_direct_proxy": "VPN → Напрямую → Прокси",
    "vpn_proxy_direct": "VPN → Прокси → Напрямую",
    "proxy_direct_vpn": "Прокси → Напрямую → VPN",
    "proxy_vpn_direct": "Прокси → VPN → Напрямую",
}


def order_key(order: list[str]) -> str:
    """Ключ пресета для сохранённого порядка; незнакомый — первый пресет.

    Порядок мог прийти из другой версии или из испорченного файла.
    """
    for key, preset in ORDER_PRESETS.items():
        if preset == list(order):
            return key
    return next(iter(ORDER_PRESETS))


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


def geo_summary(catalog: GeoCatalog) -> str:
    """Строка состояния геобаз для страницы настроек «Версия»."""
    if not catalog.geosite and not catalog.geoip:
        return "Не найдены: правила geosite: и geoip: не применяются"
    return f"geosite: {len(catalog.geosite)} категорий, geoip: {len(catalog.geoip)}"


def normalize_routing_entry(value: str) -> str:
    import ipaddress
    import re
    from urllib.parse import urlsplit

    from src.db.config import classify_routing_entry

    if value.lower().startswith(("http://", "https://")):
        try:
            parts = urlsplit(value)
            _ = parts.port
            if parts.username is not None or parts.password is not None or not parts.hostname:
                raise ValueError
            value = parts.hostname
        except ValueError:
            raise ValueError("URL правила должен содержать имя сайта без credentials") from None
    prefix, _, rest = value.partition(":")
    if prefix.lower() in ("full", "domain"):
        try:
            host = rest.lower().encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("Некорректное доменное имя") from None
        # Ядро сравнивает правило с именем в нижнем регистре и в punycode.
        # Звёздочка — синтаксис голого суффикса, здесь она была бы буквой.
        if not re.fullmatch(r"[a-z0-9_.-]+", host) or host.startswith(".") or len(host) > 253:
            raise ValueError("Некорректное правило маршрутизации")
        return f"{prefix.lower()}:{host}"
    if value.lower().startswith(
        ("domain:", "full:", "regexp:", "keyword:", "dotless:", "geosite:", "geoip:")
    ):
        if not value.partition(":")[2] or classify_routing_entry(value) is None:
            raise ValueError("Некорректное правило маршрутизации")
        return value
    try:
        ipaddress.ip_network(value, strict=False)
        return value
    except ValueError:
        pass
    try:
        host = value.lower().encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("Некорректное доменное имя") from None
    if not re.fullmatch(r"(?:\*\.)?[a-z0-9_.-]+", host) or len(host) > 253:
        raise ValueError("Введите домен, IP, CIDR или правило маршрутизации")
    return host
