"""Named pipe службы: один клиент за раз, запрос → ответ.

DACL канала: SYSTEM и администраторы — полный доступ, интерактивные
пользователи (IU) — чтение и запись. Удалённые клиенты отвергаются флагом
PIPE_REJECT_REMOTE_CLIENTS. `serve_connection` от Windows не зависит.
"""

from __future__ import annotations

import logging
import threading

from src.winsvc.dispatch import dispatch
from src.winsvc.protocol import LineReader, ProtocolError, Response, decode_request, encode

logger = logging.getLogger("tenga.winsvc.server")

PIPE_NAME = r"\\.\pipe\tenga-proxy-svc"
PIPE_SDDL = "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)"
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
# Создать канал можно, только если такого имени ещё нет: иначе процесс
# пользователя, успевший занять имя до старта службы, выдавал бы себя за неё.
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
RETRY_SECONDS = 1.0
BUFFER = 65536


def serve_connection(channel, state) -> None:
    """`channel.read()` → bytes (b"" — клиент ушёл), `channel.write(bytes)`."""
    state.client_connected()
    reader = LineReader()
    try:
        while True:
            data = channel.read()
            if not data:
                return
            for line in reader.feed(data):
                channel.write(encode(dispatch(state, decode_request(line))))
    except ProtocolError as e:
        logger.warning("Protocol violation, closing connection: %s", e)
        try:
            channel.write(encode(Response(0, False, error=f"Нарушение протокола: {e}")))
        except OSError:
            pass
    except OSError as e:
        logger.info("Client connection dropped: %s", e)
    finally:
        state.client_gone()


class _PipeChannel:
    def __init__(self, handle):
        self._handle = handle

    def read(self) -> bytes:
        import pywintypes
        import win32file

        try:
            _rc, data = win32file.ReadFile(self._handle, BUFFER)
            return bytes(data)
        except pywintypes.error:
            return b""

    def write(self, data: bytes) -> None:
        import pywintypes
        import win32file

        try:
            win32file.WriteFile(self._handle, data)
        except pywintypes.error as e:
            raise OSError(str(e)) from e


class PipeServer:
    def __init__(self, state) -> None:
        self._state = state
        self._stopping = threading.Event()

    def _create(self):
        import win32pipe
        import win32security

        attributes = win32security.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = (
            win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
                PIPE_SDDL, win32security.SDDL_REVISION_1
            )
        )
        return win32pipe.CreateNamedPipe(
            PIPE_NAME,
            win32pipe.PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            win32pipe.PIPE_TYPE_BYTE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT
            | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            BUFFER,
            BUFFER,
            0,
            attributes,
        )

    def serve_forever(self) -> None:
        import pywintypes
        import win32file
        import win32pipe

        while not self._stopping.is_set():
            try:
                handle = self._create()
            except pywintypes.error as e:
                logger.error("Cannot create the service pipe (name taken?): %s", e)
                self._stopping.wait(RETRY_SECONDS)
                continue
            try:
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except pywintypes.error as e:
                    # ERROR_PIPE_CONNECTED: клиент успел подключиться раньше вызова.
                    if e.winerror != 535:
                        raise
                if self._stopping.is_set():
                    return
                serve_connection(_PipeChannel(handle), self._state)
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except pywintypes.error:
                    pass
                win32file.CloseHandle(handle)

    def stop(self) -> None:
        """Разбудить ConnectNamedPipe пустым подключением."""
        self._stopping.set()
        try:
            with open(PIPE_NAME, "r+b", buffering=0):
                pass
        except OSError:
            pass
