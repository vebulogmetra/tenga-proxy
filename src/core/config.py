from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """Check if running as a frozen executable (PyInstaller)."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _is_appimage() -> bool:
    """Check if running from AppImage."""
    return "TENGA_CONFIG_DIR" in os.environ or os.environ.get("APPIMAGE") is not None


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
    env_dir = os.environ.get("TENGA_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)

    # Frozen or AppImage: use XDG config dir
    if _is_frozen() or _is_appimage():
        xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return Path(xdg_config) / "tenga-proxy"

    # Development: use ./core
    return Path(__file__).resolve().parent.parent.parent / "core"


def _get_log_dir() -> Path:
    """Get log directory."""
    if _is_frozen() or _is_appimage():
        return _get_config_dir() / "logs"
    return Path(__file__).resolve().parent.parent.parent / "logs"


BUNDLE_DIR: Path = _get_bundle_dir()
PROJECT_ROOT: Path = (
    Path(__file__).resolve().parent.parent.parent if not _is_frozen() else BUNDLE_DIR
)
CORE_DIR: Path = _get_config_dir()
CORE_BIN_DIR: Path = BUNDLE_DIR / "core" / "bin" if _is_frozen() else CORE_DIR / "bin"
XRAY_BINARY_NAME: str = "xray"

LOG_DIR: Path = _get_log_dir()
GUI_LOG_FILE: Path = LOG_DIR / "tenga_gui.log"
CLI_LOG_FILE: Path = LOG_DIR / "tenga_cli.log"
XRAY_LOG_FILE: Path = LOG_DIR / "xray.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)
CORE_DIR.mkdir(parents=True, exist_ok=True)


def get_lock_file(config_dir: Path | None = None) -> Path:
    """Get lock file path.

    Args:
        config_dir: Optional configuration directory. If None, uses default CORE_DIR.

    Returns:
        Path to lock file
    """
    if config_dir:
        return config_dir / "tenga-proxy.lock"
    return CORE_DIR / "tenga-proxy.lock"


# Stats API
DEFAULT_STATS_API_ADDR: str = "127.0.0.1:10085"
DEFAULT_STATS_API_TOKEN: str = ""


def find_xray_binary() -> str | None:
    """
    Find xray-core binary.

    Search priority:
    1. Bundled xray (in PyInstaller bundle)
    2. xray in core/bin/ directory
    3. xray in user config dir
    4. xray in system PATH

    Returns:
        Path to xray or None if not found
    """
    search_paths = []

    if _is_frozen():
        bundled = BUNDLE_DIR / "core" / "bin" / XRAY_BINARY_NAME
        search_paths.append(bundled)

    search_paths.append(CORE_BIN_DIR / XRAY_BINARY_NAME)

    if _is_frozen():
        user_bin = CORE_DIR / "bin" / XRAY_BINARY_NAME
        search_paths.append(user_bin)

    for xray_path in search_paths:
        if xray_path.exists() and xray_path.is_file():
            try:
                result = subprocess.run(
                    [str(xray_path), "version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return str(xray_path)
            except Exception:
                pass

    try:
        result = subprocess.run(
            [XRAY_BINARY_NAME, "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return XRAY_BINARY_NAME
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
