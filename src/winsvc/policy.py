"""Что служба соглашается запустить от имени SYSTEM.

Канал открыт интерактивным пользователям, поэтому конфиг от клиента считается
недоверенным. Запрещено всё, что дало бы через ядро доступ к файлам или
открыло бы порт наружу: пути к файлам, входы не на loopback, внешние геобазы
вне каталога ядра. Пути логов убираются — вывод ядра служба пишет в свой лог.
Остальные смысловые инварианты проверяет тот же `validate_session_config`, что
и GUI перед запуском.
"""

from __future__ import annotations

import copy
import ipaddress
from typing import Any

from src.core.config_validator import validate_session_config

ALLOWED_INBOUNDS = frozenset({"tun", "socks", "http", "mixed", "dokodemo-door"})
# Ключи, значение которых ядро открывает как файл на чтение или запись.
FILE_KEYS = frozenset({"certificateFile", "keyFile", "masterKeyLog"})
API_TAG = "api"


class PolicyError(ValueError):
    """Конфиг не может быть запущен службой."""


def _is_loopback(listen: str) -> bool:
    try:
        return ipaddress.ip_address(listen).is_loopback
    except ValueError:
        return listen == "localhost"


def _walk(node: Any, problems: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FILE_KEYS:
                problems.append(f"file reference is not allowed: {key}")
            _walk(value, problems)
    elif isinstance(node, list):
        for value in node:
            _walk(value, problems)
    elif isinstance(node, str) and node.startswith("ext:"):
        filename = node[4:].split(":", 1)[0]
        if "/" in filename or "\\" in filename or ".." in filename:
            problems.append(f"external geo file outside the core directory: {node}")


def sanitize_core_config(config: dict) -> dict:
    result = copy.deepcopy(config)
    problems: list[str] = []

    result["inbounds"] = [
        inbound for inbound in result.get("inbounds", []) if inbound.get("tag") != API_TAG
    ]
    for inbound in result["inbounds"]:
        protocol = inbound.get("protocol")
        if protocol not in ALLOWED_INBOUNDS:
            problems.append(f"inbound protocol is not allowed: {protocol}")
        # Без `listen` ядро слушает на всех интерфейсах.
        if protocol != "tun" and not _is_loopback(str(inbound.get("listen", "0.0.0.0"))):
            problems.append(f"inbound must listen on loopback: {inbound.get('tag')}")

    log = result.get("log")
    if isinstance(log, dict):
        log.pop("access", None)
        log.pop("error", None)

    _walk(result, problems)
    problems.extend(validate_session_config(result))
    if problems:
        raise PolicyError("; ".join(problems))
    return result
