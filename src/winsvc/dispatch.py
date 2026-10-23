"""Запрос протокола → метод `ServiceState` → ответ."""

from __future__ import annotations

import logging

from src.winsvc.protocol import Request, Response
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.winsvc.dispatch")

# Команда → (метод, обязательные аргументы).
ROUTES = {
    "hello": ("hello", ("version",)),
    "core.start": ("core_start", ("config",)),
    "core.stop": ("core_stop", ()),
    "core.status": ("core_status", ()),
    "core.stats": ("core_stats", ()),
    "routes.apply": ("routes_apply", ("tun_name", "proxy_host")),
    "routes.restore": ("routes_restore", ()),
    "dns.apply": ("dns_apply", ("tun_name",)),
}


def dispatch(state, request: Request) -> Response:
    route = ROUTES.get(request.cmd)
    if route is None:
        return Response(request.id, False, error=f"Команда не поддерживается: {request.cmd}")
    method, required = route
    missing = [name for name in required if name not in request.args]
    if missing:
        return Response(request.id, False, error=f"Нет аргументов: {', '.join(missing)}")
    try:
        result = getattr(state, method)(**{name: request.args[name] for name in required})
    except ServiceError as e:
        return Response(request.id, False, error=str(e))
    except Exception:
        logger.exception("Command %s failed", request.cmd)
        return Response(request.id, False, error="Внутренняя ошибка службы, подробности в её логе")
    return Response(request.id, True, result=result or {})
