"""Направление системного DNS в TUN.

На системах с systemd-resolved приложения спрашивают заглушку `127.0.0.53`, а
она — DNS-сервер физического интерфейса, причём мимо таблицы маршрутов. До TUN
такие запросы не доходят, и правило перехвата в конфиге ядра остаётся без дела.
Здесь TUN-интерфейсу назначается DNS-сервер и домен `~.`: резолвер начинает
слать все запросы через него.

Отменять ничего не нужно: настройки привязаны к интерфейсу и исчезают вместе с
ним, когда ядро останавливается.
"""

from __future__ import annotations

import logging
import re
import shutil

from src.sys.tun_route import _run_command, _run_helper

logger = logging.getLogger("tenga.sys.tun_dns")

# Адрес, который объявляется DNS-сервером TUN-интерфейса. Запрос к нему
# перехватывает правило `tun-in:53 → dns-out`, до самого адреса он не доходит.
# Публичный адрес выбран на случай, если перехват не сработает: тогда запрос
# уйдёт через прокси и всё равно получит ответ.
TUN_DNS_ADDRESS = "1.1.1.1"
# «Все домены»: с ним интерфейс выигрывает у DNS физического интерфейса.
ALL_DOMAINS = "~."


def route_system_dns_to_tun(tun_name: str) -> tuple[bool, str]:
    """Попросить systemd-resolved слать запросы через TUN-интерфейс.

    Returns:
        (успех, причина отказа). Отказ не фатален: DNS идёт как раньше, мимо туннеля.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.:-]{0,31}", tun_name):
        return False, "некорректное имя TUN-интерфейса"
    if not shutil.which("resolvectl"):
        return False, "resolvectl не найден: система без systemd-resolved"

    ok, error = _run_helper("dns", [tun_name])
    if ok:
        logger.info("Системный DNS направлен в %s", tun_name)
        return True, ""

    commands = [
        ["dns", tun_name, TUN_DNS_ADDRESS],
        ["domain", tun_name, ALL_DOMAINS],
    ]
    # Старый helper действия `dns` не знает. Пробуем сами: сначала без прав (вдруг
    # разрешено политикой), затем через sudo — оба раза без запроса пароля.
    prefixes = [["resolvectl", "--no-ask-password"]]
    if shutil.which("sudo"):
        prefixes.append(["sudo", "-n", "resolvectl"])

    for prefix in prefixes:
        for args in commands:
            ok, _out, command_error = _run_command([*prefix, *args])
            if not ok:
                error = command_error or error
                break
        else:
            logger.info("Системный DNS направлен в %s", tun_name)
            return True, ""

    return False, error or "не удалось настроить systemd-resolved"
