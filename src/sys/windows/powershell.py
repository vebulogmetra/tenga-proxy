"""Запуск PowerShell-скрипта с выводом JSON.

Вывод `netsh` и `route print` переведён на язык системы, а объекты PowerShell
сериализуются одинаково на любой локали.
"""

from __future__ import annotations

import logging
import subprocess

from src.core.platform_info import no_window

logger = logging.getLogger("tenga.sys.powershell")


def run_json(script: str, timeout: int = 15) -> str:
    """Stdout скрипта; пустая строка при любой ошибке."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
            **no_window(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("PowerShell failed: %s", e)
        return ""
    if result.returncode != 0:
        logger.warning("PowerShell returned %s: %s", result.returncode, result.stderr.strip())
        return ""
    return result.stdout
