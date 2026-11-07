"""Запуск установщика Inno Setup с UAC и перезапуск приложения после него.

Перезапуск делает скрытый PowerShell от имени пользователя: пункт `[Run]` с
`runasoriginaluser` у установщика, запущенного через `runas`, стартовал бы
новую версию с повышенными правами. См.
docs/plans/2026-11-07-windows-self-update-design.md.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from src.core.app_installer import InstallCancelled
from src.core.platform_info import no_window

logger = logging.getLogger("tenga.sys.app_install")

INSTALLER_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1


def can_self_update() -> bool:
    """Только собранное приложение: из исходников установщик ставить некуда."""
    return bool(getattr(sys, "frozen", False))


def relaunch_command(installer_pid: int, executable: str) -> list[str]:
    """PowerShell ждёт выхода установщика и запускает приложение от пользователя.

    `Get-Process -Id` видит процесс любого пользователя: установщик могли
    поднять под другой учётной записью администратора.
    """
    quoted = executable.replace("'", "''")
    script = (
        f"while (Get-Process -Id {int(installer_pid)} -ErrorAction SilentlyContinue) "
        "{ Start-Sleep -Milliseconds 500 }; "
        f"Start-Process -FilePath '{quoted}'"
    )
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-Command",
        script,
    ]


def _runas(path: str, parameters: str) -> int:
    """ShellExecuteExW с глаголом runas; возвращает PID установщика."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = path
    info.lpParameters = parameters
    info.nShow = SW_SHOWNORMAL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise InstallCancelled("Пользователь отказал в UAC")
        raise OSError(error, "ShellExecuteExW failed")
    try:
        return int(kernel32.GetProcessId(info.hProcess))
    finally:
        kernel32.CloseHandle(info.hProcess)


def _spawn(command: list[str]) -> None:
    # Без наследования дескрипторов и окна: наблюдатель переживает выход приложения.
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **no_window(),
    )


def launch_installer(
    path: Path,
    *,
    runas: Callable[[str, str], int] = _runas,
    spawn: Callable[[list[str]], None] = _spawn,
    executable: str | None = None,
) -> None:
    """Запустить установщик с UAC и оставить наблюдателя перезапуска.

    Отказ в UAC — `InstallCancelled`, приложение работает дальше. После
    успеха вызывающий код выходит сам.
    """
    pid = runas(str(path), INSTALLER_ARGS)
    logger.info("Installer started, pid %s", pid)
    spawn(relaunch_command(pid, executable or sys.executable))
