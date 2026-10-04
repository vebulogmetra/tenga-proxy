"""HTTP-проба через локальный inbound ядра.

Общая для пакетного замера задержки и для проверки рабочего соединения: оба
ходят через HTTP-inbound на 127.0.0.1, закрытый одноразовыми учётными данными.
Без них любой процесс на машине мог бы пользоваться проверяемыми профилями.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from statistics import median
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger("tenga.core.http_probe")

LOOPBACK = "127.0.0.1"
PROXY_AUTH_REQUIRED = 407


@dataclass(frozen=True)
class ProbeCredentials:
    """Логин и пароль HTTP-inbound'а, живут одну сессию ядра."""

    user: str
    password: str

    @classmethod
    def generate(cls) -> ProbeCredentials:
        return cls(user=secrets.token_hex(8), password=secrets.token_urlsafe(24))


@dataclass(frozen=True)
class ProbeEndpoint:
    """Куда стучаться пробе: порт на loopback и учётные данные."""

    port: int
    credentials: ProbeCredentials
    host: str = LOOPBACK

    @property
    def proxy_url(self) -> str:
        user = quote(self.credentials.user, safe="")
        password = quote(self.credentials.password, safe="")
        return f"http://{user}:{password}@{self.host}:{self.port}"


def build_probe_inbound(tag: str, endpoint: ProbeEndpoint) -> dict[str, Any]:
    """HTTP-inbound для пробы. Без учётных данных не создаётся."""
    credentials = endpoint.credentials
    if not credentials.user or not credentials.password:
        raise ValueError(f"inbound {tag} не создаётся без учётных данных")

    return {
        "tag": tag,
        "listen": endpoint.host,
        "port": endpoint.port,
        "protocol": "http",
        "settings": {
            "accounts": [{"user": credentials.user, "pass": credentials.password}],
        },
    }


def _is_success(status_code: int) -> bool:
    # 4xx отдаёт целевой сайт — значит, туннель до него дошёл. Исключение — 407:
    # его отдаёт сам inbound при неверных учётных данных. 5xx ядро возвращает,
    # когда не достучалось до сервера профиля.
    return 200 <= status_code < 500 and status_code != PROXY_AUTH_REQUIRED


def measure_latency(
    endpoint: ProbeEndpoint,
    url: str,
    *,
    timeout: float = 3.0,
    probes: int = 3,
) -> int:
    """Медиана задержки HEAD-запросов через inbound в миллисекундах, -1 при отказе.

    Первый же неудачный запрос без единого успешного прекращает замер: мёртвый
    сервер иначе съедал бы таймаут `probes` раз.
    """
    proxies = {"http": endpoint.proxy_url, "https": endpoint.proxy_url}
    samples: list[int] = []

    with requests.Session() as session:
        # Переменные окружения и системный прокси не должны увести запрос мимо
        # проверяемого inbound'а.
        session.trust_env = False

        for index in range(max(1, probes)):
            started_ns = time.perf_counter_ns()
            separator = "&" if "?" in url else "?"
            probe_url = f"{url}{separator}cb={started_ns}_{index}"
            try:
                response = session.head(
                    probe_url,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=False,
                )
            except requests.exceptions.RequestException as e:
                logger.debug("Probe via port %s failed: %s", endpoint.port, type(e).__name__)
                if not samples:
                    return -1
                continue

            elapsed_ms = (time.perf_counter_ns() - started_ns) // 1_000_000
            if _is_success(response.status_code):
                samples.append(int(elapsed_ms))
            elif not samples:
                logger.debug("Probe via port %s got status %s", endpoint.port, response.status_code)
                return -1

    return int(median(samples)) if samples else -1
