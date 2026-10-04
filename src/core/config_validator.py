"""Проверка готового конфига сессии перед запуском ядра.

Ядро проверяет схему, но не смысл: конфиг, где весь трафик идёт мимо прокси или
DNS ходит по кругу, оно примет молча. Здесь — инварианты, нарушение которых
означает ошибку сборки; с таким конфигом подключение не начинается.

Проверяется только то, что собирает `config_builder`. Пробные конфиги замера
задержки сюда не попадают.
"""

from __future__ import annotations

import ipaddress
from typing import Any

# Протоколы, которым нельзя быть выходом по умолчанию.
_NOT_A_PROXY = frozenset({"freedom", "blackhole", "dns"})
# Ключи правила, не являющиеся условием: правило только из них ловит всё подряд.
_NOT_A_CONDITION = frozenset({"type", "outboundTag", "network", "ruleTag"})
# Сети, которым нечего делать нигде, кроме direct.
_LOOPBACK = frozenset({"127.0.0.0/8", "::1/128", "geoip:private"})

TUN_INBOUND_TAG = "tun-in"
DNS_OUT_TAG = "dns-out"
LOCALHOST = "localhost"


def _dns_addresses(config: dict[str, Any]) -> list[str]:
    servers = config.get("dns", {}).get("servers", [])
    return [s if isinstance(s, str) else s.get("address", "") for s in servers]


def _check_outbounds(config: dict[str, Any]) -> list[str]:
    outbounds = config.get("outbounds") or []
    if not outbounds:
        return ["в конфиге нет ни одного outbound"]
    protocol = outbounds[0].get("protocol")
    if protocol in _NOT_A_PROXY:
        return [
            f"первый outbound — {protocol}: он выход по умолчанию, "
            "и весь несопоставленный трафик ушёл бы мимо прокси"
        ]
    return []


def _check_rules(config: dict[str, Any]) -> list[str]:
    outbounds = config.get("outbounds") or []
    known_tags = {o.get("tag") for o in outbounds}
    default_tag = outbounds[0].get("tag") if outbounds else None
    violations: list[str] = []

    for rule in config.get("routing", {}).get("rules", []):
        target = rule.get("outboundTag")
        if target not in known_tags:
            violations.append(f"правило ведёт в несуществующий outbound «{target}»")
            continue
        if set(rule) <= _NOT_A_CONDITION and target != default_tag:
            violations.append(
                f"правило без условий ведёт в «{target}»: мимо прокси ушёл бы весь трафик"
            )
        if target != "direct":
            for network in _LOOPBACK.intersection(rule.get("ip", [])):
                violations.append(f"{network} направлен в «{target}», а не напрямую")
    return violations


def _check_dns_interception(config: dict[str, Any]) -> list[str]:
    """Инварианты перехвата DNS; без outbound `dns-out` проверять нечего."""
    if not any(o.get("tag") == DNS_OUT_TAG for o in config.get("outbounds") or []):
        return []

    violations: list[str] = []
    rules = config.get("routing", {}).get("rules", [])
    first = rules[0] if rules else {}
    if not (
        first.get("outboundTag") == DNS_OUT_TAG
        and str(first.get("port")) == "53"
        and TUN_INBOUND_TAG in first.get("inboundTag", [])
    ):
        violations.append("правило перехвата DNS должно стоять первым")

    if LOCALHOST in _dns_addresses(config):
        violations.append("при перехвате DNS сервер localhost дал бы петлю запросов")

    dns_tag = config.get("dns", {}).get("tag")
    if not dns_tag or not any(
        dns_tag in rule.get("inboundTag", []) and rule.get("outboundTag") == "direct"
        for rule in rules
    ):
        violations.append(
            f"нет правила для собственных запросов DNS-модуля ({dns_tag or 'без тега'})"
        )
    return violations


def validate_session_config(config: dict[str, Any]) -> list[str]:
    """Нарушения, с которыми конфиг запускать нельзя; пустой список — конфиг годен."""
    if not config.get("outbounds"):
        # Остальные проверки без outbound'ов дали бы только шум.
        return _check_outbounds(config)
    return [
        *_check_outbounds(config),
        *_check_rules(config),
        *_check_dns_interception(config),
    ]


def exposed_inbounds(config: dict[str, Any]) -> list[str]:
    """Локальные входы, слушающие не на loopback: открытый прокси для всей сети.

    Это не нарушение — адрес задаёт пользователь, — но в журнале должно быть видно.
    """
    exposed: list[str] = []
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") not in ("socks", "http"):
            continue
        listen = inbound.get("listen") or "0.0.0.0"
        try:
            loopback = ipaddress.ip_address(listen).is_loopback
        except ValueError:
            loopback = listen == LOCALHOST
        if not loopback:
            exposed.append(f"{inbound.get('protocol')} {listen}:{inbound.get('port')}")
    return exposed
