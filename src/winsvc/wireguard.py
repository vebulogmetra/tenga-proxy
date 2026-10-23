"""Туннели WireGuard для Windows: что есть и как поднять.

Конфигурации лежат в каталоге данных WireGuard зашифрованными DPAPI и
доступны только SYSTEM, поэтому список и управление идут из службы. Служба
туннеля `WireGuardTunnel$<имя>` существует, пока туннель поднят.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Правило имён самого WireGuard для Windows.
_NAME = re.compile(r"[a-zA-Z0-9_=+.-]{1,32}")
SUFFIX = ".conf.dpapi"


def _program_files() -> Path:
    return Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))


def default_exe() -> str:
    return str(_program_files() / "WireGuard" / "wireguard.exe")


def default_config_dir() -> Path:
    return _program_files() / "WireGuard" / "Data" / "Configurations"


def validate_name(name: str) -> str:
    if not _NAME.fullmatch(name or ""):
        raise ValueError(f"bad WireGuard tunnel name: {name!r}")
    return name


def service_name(name: str) -> str:
    return f"WireGuardTunnel${validate_name(name)}"


def list_tunnels(config_dir: Path | None = None) -> list[str]:
    directory = config_dir or default_config_dir()
    try:
        files = sorted(directory.iterdir())
    except OSError:
        return []
    names = [path.name[: -len(SUFFIX)] for path in files if path.name.endswith(SUFFIX)]
    return [name for name in names if _NAME.fullmatch(name)]


def up_command(name: str, *, exe: str | None = None, config_dir: Path | None = None) -> list[str]:
    config = (config_dir or default_config_dir()) / f"{validate_name(name)}{SUFFIX}"
    return [exe or default_exe(), "/installtunnelservice", str(config)]


def down_command(name: str, *, exe: str | None = None) -> list[str]:
    return [exe or default_exe(), "/uninstalltunnelservice", validate_name(name)]
