"""Клиент службы Tenga Proxy для GUI.

Подключение ленивое и одно на процесс: при первом вызове служба запускается
через SCM (если остановлена), затем `hello` сверяет версии. Обрыв канала
сбрасывает подключение, следующий вызов откроет его заново. Вызовы
сериализуются замком: канал синхронный, запрос → ответ.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time

from src import __version__
from src.winsvc.protocol import LineReader, Request, decode_response, encode
from src.winsvc.state import ServiceError

logger = logging.getLogger("tenga.sys.service_client")

UNAVAILABLE = "Служба Tenga Proxy недоступна: переустановите приложение"


class ServiceUnavailable(ServiceError):
    pass


class _PipeFile:
    def __init__(self):
        from src.winsvc.server import PIPE_NAME

        self._file = open(PIPE_NAME, "r+b", buffering=0)

    def read(self) -> bytes:
        return self._file.read(65536)

    def write(self, data: bytes) -> None:
        self._file.write(data)

    def close(self) -> None:
        self._file.close()


def _start_service() -> None:
    import win32serviceutil

    from src.winsvc.service import SERVICE_NAME

    try:
        win32serviceutil.StartService(SERVICE_NAME)
    except Exception as e:
        # 1056: уже запущена — это нормально.
        if getattr(e, "winerror", None) != 1056:
            logger.debug("StartService: %s", e)


class ServiceClient:
    def __init__(self, *, opener=_PipeFile, starter=_start_service, connect_timeout: float = 10.0):
        self._opener = opener
        self._starter = starter
        self._connect_timeout = connect_timeout
        self._channel = None
        self._reader = LineReader()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def _connect(self) -> None:
        self._starter()
        deadline = time.monotonic() + self._connect_timeout
        while True:
            try:
                self._channel = self._opener()
                break
            except OSError as e:
                if time.monotonic() >= deadline:
                    raise ServiceUnavailable(UNAVAILABLE) from e
                time.sleep(0.2)
        self._reader = LineReader()
        self._exchange("hello", {"version": __version__})

    def _exchange(self, cmd: str, args: dict) -> dict:
        request = Request(next(self._ids), cmd, args)
        self._channel.write(encode(request))
        while True:
            data = self._channel.read()
            if not data:
                raise OSError("service closed the connection")
            lines = self._reader.feed(data)
            if lines:
                response = decode_response(lines[0])
                if not response.ok:
                    raise ServiceError(response.error)
                return response.result

    def call(self, cmd: str, **args) -> dict:
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._channel is None:
                        self._connect()
                    return self._exchange(cmd, args)
                except OSError as e:
                    self._drop()
                    if attempt == 2:
                        raise ServiceUnavailable(UNAVAILABLE) from e
        raise AssertionError("unreachable")

    def _drop(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except OSError:
                pass
        self._channel = None

    def close(self) -> None:
        with self._lock:
            self._drop()


_client: ServiceClient | None = None
_client_lock = threading.Lock()


def get_client() -> ServiceClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ServiceClient()
        return _client
