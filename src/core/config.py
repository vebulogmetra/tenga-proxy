from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.core import platform_info
from src.core.platform_info import no_window

# Куда исходники кладёт deb-пакет (core/scripts/build_deb.sh).
PACKAGE_DIR = Path("/usr/lib/tenga-proxy")


def _is_frozen() -> bool:
    """Check if running as a frozen executable (PyInstaller)."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _uses_user_dirs() -> bool:
    """Конфигурация и логи — в каталоге пользователя, а не рядом с исходниками.

    Так при запуске из deb-пакета (в /usr/lib писать нельзя) и когда каталог
    задан переменной `TENGA_CONFIG_DIR`.
    """
    return "TENGA_CONFIG_DIR" in os.environ or (
        not _is_frozen() and _get_bundle_dir() == PACKAGE_DIR
    )


def _get_bundle_dir() -> Path:
    """Get directory where bundled resources are located."""
    if _is_frozen():
        return Path(sys._MEIPASS)  # type: ignore
    return Path(__file__).resolve().parent.parent.parent


def _windows_dir(variable: str, fallback: str) -> Path:
    """Каталог из переменной окружения Windows (`APPDATA`, `LOCALAPPDATA`)."""
    return Path(os.environ.get(variable) or os.path.expanduser(fallback))


def _get_config_dir() -> Path:
    """Get configuration directory.

    When running frozen on Windows: %APPDATA%\\tenga-proxy
    When running frozen or from the deb package: ~/.config/tenga-proxy
    When running from source: ./core
    Environment variable TENGA_CONFIG_DIR takes priority.
    """
    env_dir = os.environ.get("TENGA_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)

    if _is_frozen() and platform_info.IS_WINDOWS:
        return _windows_dir("APPDATA", "~/AppData/Roaming") / "tenga-proxy"

    # Frozen or deb package: use XDG config dir
    if _is_frozen() or _uses_user_dirs():
        xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return Path(xdg_config) / "tenga-proxy"

    # Development: use ./core
    return Path(__file__).resolve().parent.parent.parent / "core"


def _get_log_dir() -> Path:
    """Get log directory."""
    if _is_frozen() and platform_info.IS_WINDOWS and "TENGA_CONFIG_DIR" not in os.environ:
        # Логи не роуминговые: им место в Local, а не в Roaming.
        return _windows_dir("LOCALAPPDATA", "~/AppData/Local") / "tenga-proxy" / "logs"
    if _is_frozen() or _uses_user_dirs():
        return _get_config_dir() / "logs"
    return Path(__file__).resolve().parent.parent.parent / "logs"


BUNDLE_DIR: Path = _get_bundle_dir()
PROJECT_ROOT: Path = (
    Path(__file__).resolve().parent.parent.parent if not _is_frozen() else BUNDLE_DIR
)
CORE_DIR: Path = _get_config_dir()
CORE_BIN_DIR: Path = BUNDLE_DIR / "core" / "bin" if _is_frozen() else CORE_DIR / "bin"
XRAY_BINARY_NAME: str = "xray.exe" if platform_info.IS_WINDOWS else "xray"

LOG_DIR: Path = _get_log_dir()
GUI_LOG_FILE: Path = LOG_DIR / "tenga_gui.log"
CLI_LOG_FILE: Path = LOG_DIR / "tenga_cli.log"
XRAY_LOG_FILE: Path = LOG_DIR / "xray.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)
CORE_DIR.mkdir(parents=True, exist_ok=True)


def get_asset_path(name: str) -> Path:
    """Get path to a bundled asset file (icons, images).

    Resolves to <bundle>/assets/<name>. Works in both dev and frozen modes.
    """
    return BUNDLE_DIR / "assets" / name


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
    1. Bundled xray (PyInstaller bundle, deb package or source tree core/bin/)
    2. xray in the config dir bin/
    3. xray in system PATH

    Ядро из комплекта идёт первым: в deb-пакете только ему postinst выдал
    cap_net_admin, а копия в ~/.config/tenga-proxy/bin — наследие AppImage.

    Returns:
        Path to xray or None if not found
    """
    search_paths = [
        BUNDLE_DIR / "core" / "bin" / XRAY_BINARY_NAME,
        CORE_BIN_DIR / XRAY_BINARY_NAME,
    ]
    if _is_frozen():
        search_paths.append(CORE_DIR / "bin" / XRAY_BINARY_NAME)

    for xray_path in dict.fromkeys(search_paths):
        if xray_path.exists() and xray_path.is_file():
            try:
                result = subprocess.run(
                    [str(xray_path), "version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **no_window(),
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
            **no_window(),
        )
        if result.returncode == 0:
            return XRAY_BINARY_NAME
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return None


def is_packaged() -> bool:
    """Запуск из установленного deb-пакета, а не из дерева исходников."""
    return not _is_frozen() and BUNDLE_DIR == PACKAGE_DIR


def init_config_files() -> None:
    """Initialize default config files if they don't exist.

    Copies default files from bundle to user config directory on first run.
    """
    if not _is_frozen():
        return
