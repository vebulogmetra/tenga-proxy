"""Pid работающего ядра — на случай падения приложения.

xray запускается без PDEATHSIG: после SIGKILL приложения он живёт дальше с
TUN-интерфейсом и маршрутами. При следующем старте его нужно погасить до
возврата маршрутов, иначе `recover_tun_routes` вернёт маршрут под живым ядром.

Процесс ищется через `/proc`: psutil в зависимостях deb-пакета нет. На Windows
каталога нет, и `kill_orphan` ничего не делает: сетью там управляет служба.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path

from src.core.config import CORE_DIR

logger = logging.getLogger("tenga.core.core_pid")

PID_FILE: Path = CORE_DIR / "xray.pid"

_TERMINATE_TIMEOUT = 5.0
_POLL_INTERVAL = 0.1
_DELETED_SUFFIX = " (deleted)"


def remember(pid: int, binary: str) -> None:
    try:
        PID_FILE.write_text(json.dumps({"pid": pid, "binary": os.path.realpath(binary)}))
    except OSError:
        logger.debug("Cannot write the core pid file", exc_info=True)


def forget() -> None:
    PID_FILE.unlink(missing_ok=True)


def _process_binary(pid: int) -> str | None:
    """Путь к бинарнику процесса; None, если процесса нет или он чужой."""
    try:
        link = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None
    return link.removesuffix(_DELETED_SUFFIX)


def _gone_within(pid: int, binary: str, timeout: float) -> bool:
    for _ in range(int(timeout / _POLL_INTERVAL)):
        if _process_binary(pid) != binary:
            return True
        time.sleep(_POLL_INTERVAL)
    return _process_binary(pid) != binary


def kill_orphan() -> bool:
    """Погасить ядро прошлого сеанса, если этот pid всё ещё наш бинарник."""
    try:
        text = PID_FILE.read_text()
    except OSError:
        return False
    forget()
    try:
        data = json.loads(text)
        pid, binary = int(data["pid"]), str(data["binary"])
    except (ValueError, KeyError, TypeError):
        logger.warning("Core pid file is malformed, dropped")
        return False
    if _process_binary(pid) != binary:
        return False

    logger.warning("Orphaned xray-core %s from a crashed session, terminating", pid)
    try:
        os.kill(pid, signal.SIGTERM)
        if not _gone_within(pid, binary, _TERMINATE_TIMEOUT):
            os.kill(pid, signal.SIGKILL)
    except OSError as e:
        logger.warning("Could not stop the orphaned xray-core: %s", e)
        return False
    return True
