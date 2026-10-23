"""Единственный экземпляр на Windows: именованный mutex.

Mutex принадлежит процессу и исчезает вместе с ним, поэтому «устаревших»
блокировок, как с файлом на Linux, не бывает. Имя зависит от каталога
конфигурации: два экземпляра с разными каталогами живут рядом, как на Linux.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger("tenga.sys.single_instance")

ERROR_ALREADY_EXISTS = 183


def mutex_name(lock_file: Path) -> str:
    digest = hashlib.sha1(str(lock_file).lower().encode("utf-8")).hexdigest()[:12]
    return f"Local\\ru.tenga.Proxy-{digest}"


class _Kernel32:
    """Тонкая обёртка над kernel32; импорт ctypes.windll — только на Windows."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self._dll.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        self._dll.CreateMutexW.restype = wintypes.HANDLE
        self._dll.CloseHandle.argtypes = [wintypes.HANDLE]

    def create_mutex(self, name: str) -> tuple[int, bool]:
        handle = self._dll.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(self._ctypes.get_last_error(), "CreateMutexW failed")
        return handle, self._ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def close(self, handle: int) -> None:
        self._dll.CloseHandle(handle)


class SingleInstance:
    """Same interface as the Linux file lock."""

    def __init__(self, lock_file: Path, *, kernel=None):
        self._name = mutex_name(lock_file)
        self._kernel = kernel
        self._handle: int | None = None

    def _api(self):
        if self._kernel is None:
            self._kernel = _Kernel32()
        return self._kernel

    def is_running(self) -> bool:
        """Держит ли mutex другой процесс: открыть и сразу закрыть."""
        if self._handle is not None:
            return False
        handle, already = self._api().create_mutex(self._name)
        self._api().close(handle)
        return already

    def acquire(self) -> bool:
        try:
            handle, already = self._api().create_mutex(self._name)
        except OSError as e:
            logger.error("Error acquiring mutex: %s", e)
            return False
        if already:
            self._api().close(handle)
            return False
        self._handle = handle
        logger.info("Mutex acquired: %s", self._name)
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        self._api().close(self._handle)
        self._handle = None
        logger.info("Mutex released")

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another instance is already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
