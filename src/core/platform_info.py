"""Какая ОС под приложением и как на ней запускать дочерние процессы.

Код в `src/core` и `src/ui` читает признак в момент вызова
(`platform_info.IS_WINDOWS`, а не `from ... import IS_WINDOWS`): тесты
подменяют его и проверяют Windows-ветки на Linux.

Фасады `src/sys/*.py` — исключение: реализацию они выбирают один раз, при
импорте, и подмена признака на них не действует. Windows-реализации тесты
импортируют напрямую (`src.sys.windows.*`), а совпадение имён и сигнатур
двух реализаций проверяет `tests/test_sys_facades.py`.
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
