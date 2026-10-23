"""Точка входа tenga-proxy-svc.exe.

Без аргументов — запуск службой (диспетчер SCM). Аргументы: install, remove,
cleanup (для установщика) и debug (служба в консоли до Ctrl+C).
"""

import os
import sys
import threading
from pathlib import Path


def early_environment() -> None:
    """До первого импорта src.

    Пакет src тянет src.core.config, а тот вычисляет каталоги конфигурации и
    логов один раз, при импорте: без этого служба писала бы в профиль SYSTEM.
    Путь совпадает с src.winsvc.service.data_dir().
    """
    programdata = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    os.environ["TENGA_CONFIG_DIR"] = str(programdata / "tenga-proxy")


def main() -> int:
    early_environment()
    from src.winsvc import service

    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command in ("install", "remove", "cleanup"):
        from src.winsvc import install

        getattr(install, command)()
        return 0

    service.prepare_environment()
    if command == "debug":
        stop = threading.Event()
        try:
            service.run(stop)
        except KeyboardInterrupt:
            stop.set()
        return 0

    import servicemanager

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(service.framework_class())
    servicemanager.StartServiceCtrlDispatcher()
    return 0


if __name__ == "__main__":
    sys.exit(main())
