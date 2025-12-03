from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional


def _is_frozen() -> bool:
    """Check if running as a frozen executable (PyInstaller)."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _is_appimage() -> bool:
    """Check if running from AppImage."""
    return 'TENGA_CONFIG_DIR' in os.environ or os.environ.get('APPIMAGE') is not None


def _get_bundle_dir() -> Path:
    """Get directory where bundled resources are located."""
    if _is_frozen():
        return Path(sys._MEIPASS)  # type: ignore
    return Path(__file__).resolve().parent.parent.parent


def _get_config_dir() -> Path:
    """Get configuration directory.
    
    When running from AppImage/frozen: ~/.config/tenga-proxy
    When running from source: ./core
    Environment variable TENGA_CONFIG_DIR takes priority.
    """
    env_dir = os.environ.get('TENGA_CONFIG_DIR')
    if env_dir:
        return Path(env_dir)

    # Frozen or AppImage: use XDG config dir
    if _is_frozen() or _is_appimage():
        xdg_config = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        return Path(xdg_config) / 'tenga-proxy'

    # Development: use ./core
    return Path(__file__).resolve().parent.parent.parent / "core"


def _get_log_dir() -> Path:
    """Get log directory."""
    if _is_frozen() or _is_appimage():
        return _get_config_dir() / "logs"
    return Path(__file__).resolve().parent.parent.parent / "logs"

BUNDLE_DIR: Path = _get_bundle_dir()
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent if not _is_frozen() else BUNDLE_DIR
CORE_DIR: Path = _get_config_dir()
CORE_BIN_DIR: Path = BUNDLE_DIR / "core" / "bin" if _is_frozen() else CORE_DIR / "bin"
SINGBOX_BINARY_NAME: str = "sing-box"

LOG_DIR: Path = _get_log_dir()
GUI_LOG_FILE: Path = LOG_DIR / "tenga_gui.log"
CLI_LOG_FILE: Path = LOG_DIR / "tenga_cli.log"
SINGBOX_LOG_FILE: Path = LOG_DIR / "singbox.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)
CORE_DIR.mkdir(parents=True, exist_ok=True)

# Clash API
DEFAULT_CLASH_API_ADDR: str = "127.0.0.1:9090"
DEFAULT_CLASH_API_SECRET: str = ""


def find_singbox_binary() -> Optional[str]:
    """
    Find sing-box binary.

    Search priority:
    1. Bundled sing-box (in PyInstaller bundle)
    2. sing-box in core/bin/ directory  
    3. sing-box in user config dir
    4. sing-box in system PATH

    Returns:
        Path to sing-box or None if not found
    """
    search_paths = []

    if _is_frozen():
        bundled = BUNDLE_DIR / "core" / "bin" / SINGBOX_BINARY_NAME
        search_paths.append(bundled)

    search_paths.append(CORE_BIN_DIR / SINGBOX_BINARY_NAME)

    if _is_frozen():
        user_bin = CORE_DIR / "bin" / SINGBOX_BINARY_NAME
        search_paths.append(user_bin)

    for singbox_path in search_paths:
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


def init_config_files() -> None:
    """Initialize default config files if they don't exist.
    
    Copies default files from bundle to user config directory on first run.
    """
    if not _is_frozen():
        return
