"""Установка и удаление службы (вызывает установщик Inno Setup)."""

from __future__ import annotations

import subprocess
import sys

from src.core.platform_info import no_window
from src.winsvc.service import DESCRIPTION, DISPLAY_NAME, SERVICE_NAME

# Права на службу: SYSTEM и администраторы — полные, интерактивные
# пользователи (IU) — опрос, запуск (RP) и остановка (WP).
SERVICE_SDDL = (
    "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWRPWPLOCRRC;;;IU)"
)


def install() -> None:
    import win32service

    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        handle = win32service.CreateService(
            scm,
            SERVICE_NAME,
            DISPLAY_NAME,
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_WIN32_OWN_PROCESS,
            win32service.SERVICE_AUTO_START,
            win32service.SERVICE_ERROR_NORMAL,
            f'"{sys.executable}"',
            None,
            0,
            None,
            None,
            None,
        )
        try:
            win32service.ChangeServiceConfig2(
                handle, win32service.SERVICE_CONFIG_DESCRIPTION, DESCRIPTION
            )
            win32service.ChangeServiceConfig2(
                handle, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, True
            )
        finally:
            win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(scm)
    subprocess.run(["sc.exe", "sdset", SERVICE_NAME, SERVICE_SDDL], check=True, **no_window())
    subprocess.run(["sc.exe", "start", SERVICE_NAME], check=False, **no_window())


def remove() -> None:
    import win32serviceutil

    try:
        win32serviceutil.StopService(SERVICE_NAME)
    except Exception:
        pass
    win32serviceutil.RemoveService(SERVICE_NAME)


def cleanup() -> None:
    """Откат сети без службы: для удаления приложения, если служба сломана."""
    from src.winsvc.service import build_state, prepare_environment

    prepare_environment()
    build_state().recover()
