"""Второй запуск просит первый показать окно и открыть ссылки.

`multiprocessing.connection` даёт на Windows named pipe (`AF_PIPE`), а
`authkey` отсекает случайных собеседников: подключиться может кто угодно из
сессии, но запрос без ключа сервер отбрасывает. Сообщение — словарь
`{"uris": [str, ...]}`, всё прочее игнорируется.
"""

from __future__ import annotations

import getpass
import hashlib
import logging
import threading
from collections.abc import Callable
from multiprocessing.connection import Client, Listener

logger = logging.getLogger("tenga.sys.activation")

AUTHKEY = b"tenga-activate"


def pipe_address(lock_file: str, user: str | None = None) -> str:
    user = user or getpass.getuser()
    digest = hashlib.sha1(f"{user}|{str(lock_file).lower()}".encode()).hexdigest()[:12]
    return f"\\\\.\\pipe\\ru.tenga.Proxy-{digest}"


def send_activation(address: str, uris: list[str], *, family: str = "AF_PIPE") -> bool:
    try:
        with Client(address, family=family, authkey=AUTHKEY) as conn:
            conn.send({"uris": list(uris)})
        return True
    except (OSError, EOFError) as e:
        logger.warning("Activation request failed: %s", e)
        return False


class ActivationServer:
    """Принимает запросы в фоновом потоке и отдаёт их обработчику."""

    def __init__(
        self,
        address: str,
        on_request: Callable[[list[str]], None],
        *,
        family: str = "AF_PIPE",
    ) -> None:
        self._address = address
        self._family = family
        self._on_request = on_request
        self._listener: Listener | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        self._listener = Listener(self._address, family=self._family, authkey=AUTHKEY)
        self._thread = threading.Thread(target=self._serve, name="tenga-activation", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                with self._listener.accept() as conn:
                    message = conn.recv()
            except Exception as e:
                if not self._stopping.is_set():
                    logger.debug("Activation connection dropped: %s", e)
                continue
            if self._stopping.is_set():
                return
            uris = message.get("uris") if isinstance(message, dict) else None
            if not isinstance(uris, list) or not all(isinstance(u, str) for u in uris):
                uris = []
            self._on_request(uris)

    def stop(self) -> None:
        self._stopping.set()
        # accept() блокирует поток: будим его пустым подключением.
        send_activation(self._address, [], family=self._family)
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
