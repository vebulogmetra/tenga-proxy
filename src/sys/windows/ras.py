"""Встроенные VPN Windows (IKEv2, L2TP, SSTP, PPTP).

Список и состояние — `Get-VpnConnection`: его поля не переводятся на язык
системы. Подключение — `rasdial` с сохранёнными учётными данными; вывод
`rasdial` переведён, поэтому значение имеет только код возврата.
"""

from __future__ import annotations

import json
import logging
import subprocess

from src.core.platform_info import no_window
from src.sys.windows.powershell import run_json

logger = logging.getLogger("tenga.sys.ras")

SCRIPT = (
    # Имена подключений бывают кириллическими: вывод — в UTF-8, как в netinfo.
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    "@(@(Get-VpnConnection -ErrorAction SilentlyContinue) + "
    "@(Get-VpnConnection -AllUserConnection -ErrorAction SilentlyContinue) | "
    "ForEach-Object { @{ name = $_.Name; status = [string]$_.ConnectionStatus } }) "
    "| ConvertTo-Json -Compress"
)


def parse_connections(text: str) -> dict[str, bool]:
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return {}
    items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    return {
        str(item["name"]): item.get("status") == "Connected"
        for item in items
        if isinstance(item, dict) and item.get("name")
    }


def connections() -> dict[str, bool]:
    return parse_connections(run_json(SCRIPT))


def _rasdial(args: list[str]) -> bool:
    try:
        result = subprocess.run(
            ["rasdial", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **no_window(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("rasdial failed: %s", e)
        return False
    if result.returncode != 0:
        logger.warning("rasdial %s returned %s", args[0], result.returncode)
    return result.returncode == 0


def connect(name: str) -> bool:
    return _rasdial([name])


def disconnect(name: str) -> bool:
    return _rasdial([name, "/disconnect"])
