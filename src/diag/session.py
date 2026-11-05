"""Токен сеанса туннеля: порт DiagnosticTunnelSessionSource.kt.

Учётные данные inbound живут только здесь: ни в отчёт, ни в repr они не попадают. Смена
эндпойнта или падение ядра дают другой токен, и результат старого сеанса отбрасывается.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from src.core.http_probe import ProbeEndpoint
from src.diag.probes.support import TunnelEndpoint

_LOOPBACKS = ("127.0.0.1", "::1")


@dataclass(frozen=True, repr=False)
class TunnelSession:
    token: str
    endpoint: TunnelEndpoint

    def __repr__(self) -> str:
        return f"TunnelSession(token={self.token})"


class TunnelSessionSource:
    def __init__(self, endpoint: Callable[[], ProbeEndpoint | None]):
        self._endpoint = endpoint
        self._lock = threading.Lock()
        self._session: TunnelSession | None = None
        self._seen: ProbeEndpoint | None = None

    def current(self) -> TunnelSession | None:
        with self._lock:
            found = self._endpoint()
            if found is None or found.host not in _LOOPBACKS or not 0 < found.port < 65536:
                self._session, self._seen = None, None
            elif found != self._seen:
                self._seen = found
                self._session = TunnelSession(
                    str(uuid.uuid4()),
                    TunnelEndpoint(
                        found.port, found.credentials.user, found.credentials.password, found.host
                    ),
                )
            return self._session

    def is_current(self, expected: TunnelSession) -> bool:
        session = self.current()
        return session is not None and session.token == expected.token
