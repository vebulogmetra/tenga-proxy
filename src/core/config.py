from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
CORE_DIR: Path = PROJECT_ROOT / "core"
CORE_BIN_DIR: Path = CORE_DIR / "bin"
SINGBOX_BINARY_NAME: str = "sing-box"

LOG_DIR: Path = PROJECT_ROOT / "logs"
GUI_LOG_FILE: Path = LOG_DIR / "tenga_gui.log"
CLI_LOG_FILE: Path = LOG_DIR / "tenga_cli.log"

# Clash API
DEFAULT_CLASH_API_ADDR: str = "127.0.0.1:9090"
DEFAULT_CLASH_API_SECRET: str = ""


def find_singbox_binary() -> Optional[str]:
    """
    Find sing-box binary.

    Search priority:
    1. sing-box in core/bin/ directory
    2. sing-box in system PATH

    Returns:
        Path to sing-box or None if not found
    """
    singbox_path = CORE_BIN_DIR / SINGBOX_BINARY_NAME

    if singbox_path.exists() and singbox_path.is_file():
        try:
            result = subprocess.run(
                [str(singbox_path), "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return str(singbox_path)
        except Exception:
            pass

    try:
        result = subprocess.run(
            [SINGBOX_BINARY_NAME, "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return SINGBOX_BINARY_NAME
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return None
