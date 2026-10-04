"""Служебный inbound проверки соединения в рабочем конфиге.

Монитор проверяет прокси запросом через этот inbound. Обычным путём — через
TUN или пользовательский SOCKS/HTTP-inbound — проверять нельзя: запрос
подчинился бы правилам маршрутизации и, попав под direct-правило, прошёл бы
мимо прокси. Мёртвый сервер тогда выглядел бы живым. Правило
`health-in → proxy` стоит первым, поэтому проверка всегда идёт через сервер
профиля.
"""

from __future__ import annotations

import copy
from typing import Any

from src.core.batch_probe import reserve_ports
from src.core.http_probe import ProbeCredentials, ProbeEndpoint, build_probe_inbound

HEALTH_INBOUND_TAG = "health-in"
DEFAULT_PROXY_TAG = "proxy"
REDACTED = "***"


def new_health_endpoint() -> ProbeEndpoint:
    """Свободный порт на loopback и учётные данные на одну сессию ядра."""
    return ProbeEndpoint(port=reserve_ports(1)[0], credentials=ProbeCredentials.generate())


def attach_health_inbound(config: dict[str, Any], endpoint: ProbeEndpoint) -> dict[str, Any]:
    """Добавить в конфиг сессии inbound проверки и правило для него. Меняет `config`."""
    outbounds = config.get("outbounds") or []
    proxy_tag = (outbounds[0].get("tag") if outbounds else None) or DEFAULT_PROXY_TAG

    config.setdefault("inbounds", []).append(build_probe_inbound(HEALTH_INBOUND_TAG, endpoint))
    config.setdefault("routing", {}).setdefault("rules", []).insert(
        0,
        {"type": "field", "inboundTag": [HEALTH_INBOUND_TAG], "outboundTag": proxy_tag},
    )
    return config


def redact_health_credentials(config: dict[str, Any]) -> dict[str, Any]:
    """Копия конфига без учётных данных inbound'а проверки — для записи на диск."""
    redacted = copy.deepcopy(config)
    for inbound in redacted.get("inbounds", []):
        if inbound.get("tag") == HEALTH_INBOUND_TAG:
            inbound["settings"]["accounts"] = [{"user": REDACTED, "pass": REDACTED}]
    return redacted
