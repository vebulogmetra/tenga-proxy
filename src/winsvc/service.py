"""Служба Windows TengaProxySvc: pipe-сервер, сторож ядра, откат при старте."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

SERVICE_NAME = "TengaProxySvc"
DISPLAY_NAME = "Tenga Proxy"
DESCRIPTION = "Запускает TUN-режим Tenga Proxy: xray-core, маршруты и DNS."
# Каталог службы: журнал, логи. Пользователям — только чтение.
DATA_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FRFX;;;BU)"


def data_dir() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "tenga-proxy"


def prepare_environment() -> None:
    """До импорта src.core.config: конфигурация и логи службы — в ProgramData."""
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ["TENGA_CONFIG_DIR"] = str(directory)
    _restrict(directory)


def _restrict(directory: Path) -> None:
    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        DATA_SDDL, win32security.SDDL_REVISION_1
    )
    win32security.SetFileSecurity(
        str(directory), win32security.DACL_SECURITY_INFORMATION, descriptor
    )


def build_state():
    from src.core.xray_manager import XrayManager
    from src.winsvc.journal import Journal
    from src.winsvc.netops import NetOps
    from src.winsvc.state import ServiceState

    runner = XrayManager(binary_path=None)
    state = ServiceState(
        runner=runner, net=NetOps(), journal=Journal(data_dir() / "svc-state.json")
    )

    class _Forward(logging.Handler):
        def emit(self, record):
            state.core_output(record.getMessage())

    runner.add_output_handler(_Forward())
    return state


def run(stop_event: threading.Event) -> None:
    """Тело службы; вызывается из SvcDoRun и из `svc_main.py debug`."""
    from src.core.config import LOG_DIR
    from src.core.logging_utils import setup_logging
    from src.winsvc.server import PipeServer

    setup_logging(LOG_DIR / "tenga_service.log", level=logging.INFO)
    state = build_state()
    state.recover()
    server = PipeServer(state)
    thread = threading.Thread(target=server.serve_forever, name="pipe", daemon=True)
    thread.start()
    while not stop_event.wait(1.0):
        state.tick()
    server.stop()
    state.core_stop()


def framework_class():
    """Класс ServiceFramework; импорт pywin32 — только при запуске службы."""
    import servicemanager
    import win32service
    import win32serviceutil

    class TengaProxyService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self._stop = threading.Event()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop.set()

        def SvcDoRun(self):
            servicemanager.LogInfoMsg(f"{SERVICE_NAME} started")
            run(self._stop)

    return TengaProxyService
