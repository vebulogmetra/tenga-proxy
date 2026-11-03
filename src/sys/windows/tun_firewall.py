"""Блокировка трафика на Windows: пока её нет.

Служба откатывает маршруты при падении ядра, закрывать трафик там придётся
файрволом или WFP — отдельным этапом, см.
docs/plans/2026-11-03-tun-kill-switch-design.md.
"""

from __future__ import annotations

from src.sys.firewall_policy import FirewallPolicy


def apply_firewall(policy: FirewallPolicy) -> tuple[bool, str]:
    return True, ""


def remove_firewall() -> tuple[bool, str]:
    return True, ""
