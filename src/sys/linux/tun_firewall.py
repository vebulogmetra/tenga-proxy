"""Блокировка трафика мимо туннеля таблицей nftables `inet veblock`.

Таблицу ставит root-помощник по проверенным аргументам (см.
tun_route_helper.sh). Уровень `ipv6_only` стоит в любом сеансе TUN: IPv6 в
туннель не заворачивается и иначе ходит мимо прокси. Уровень `full` — настройка
«Блокировать трафик при обрыве»: закрыт весь прямой трафик, кроме локальной
сети, сокетов ядра (метка) и VPN сервера.
"""

from __future__ import annotations

import logging

from src.sys.firewall_policy import FirewallPolicy
from src.sys.linux.tun_route import HELPER_MISSING, _run_helper

logger = logging.getLogger("tenga.sys.tun_firewall")


def apply_firewall(policy: FirewallPolicy) -> tuple[bool, str]:
    args = policy.helper_args()
    ok, error = _run_helper("firewall-apply", args)
    if not ok:
        return False, error
    logger.info("Firewall applied: %s", " ".join(args))
    return True, ""


def remove_firewall() -> tuple[bool, str]:
    """Снять таблицу; её отсутствие — не ошибка."""
    ok, error = _run_helper("firewall-remove", [])
    if ok or error == HELPER_MISSING:
        # Без помощника таблицу некому было поставить.
        return True, ""
    return False, error
