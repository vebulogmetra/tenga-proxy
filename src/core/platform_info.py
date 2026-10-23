"""Какая ОС под приложением и как на ней запускать дочерние процессы.

Признак читается в момент вызова, а не при импорте модулей-потребителей:
тесты подменяют `IS_WINDOWS` и проверяют Windows-ветки на Linux.
"""

from __future__ import annotations

import sys

IS_WINDOWS: bool = sys.platform == "win32"

# Без этого флага каждый вызов консольной программы (xray, PowerShell) из
# оконного приложения на мгновение открывает окно консоли.
CREATE_NO_WINDOW = 0x08000000


def no_window() -> dict:
    """Аргументы subprocess, скрывающие окно консоли; вне Windows — пусто.

    На POSIX subprocess отвергает ненулевой `creationflags`, поэтому ключ
    добавляется только на Windows.
    """
    if IS_WINDOWS:
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
