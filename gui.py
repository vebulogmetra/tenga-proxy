#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

from src import __app_name__ as APP_NAME
from src import __version__ as APP_VERSION

MIN_ADWAITA = (1, 5)


def setup_early_logging():
    log_dir = os.environ.get("TENGA_CONFIG_DIR")
    if not log_dir:
        xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        log_dir = os.path.join(xdg, "tenga-proxy")

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "startup.log")

    logging.basicConfig(
        filename=log_file, level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    return logging.getLogger("startup")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tenga Proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--config-dir", type=Path, help="Директория конфигурации (по умолчанию core/)"
    )
    parser.add_argument("--no-tray", action="store_true", help="Не показывать иконку в трее")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser


def parse_args(argv: list[str] | None = None):
    """Parse the command line before GTK and the configuration are loaded.

    `--config-dir` определяет, куда пишутся стартовый лог и конфигурация,
    поэтому разбор обязан идти раньше и того, и другого.
    """
    return build_parser().parse_known_args(argv)


def adwaita_is_supported(major: int, minor: int) -> bool:
    """Check libadwaita against the minimum version the new UI needs."""
    return (major, minor) >= MIN_ADWAITA


# --- GTK bootstrap ---

logger = setup_early_logging()
logger.info("=== Tenga Proxy starting ===")
logger.info(f"Python: {sys.version}")
logger.info(f"DISPLAY: {os.environ.get('DISPLAY')}")
logger.info(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
logger.info(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE')}")

_ARGS, _EXTRA = parse_args()

if "GI_TYPELIB_PATH" not in os.environ:
    typelib_paths = [
        "/usr/lib/girepository-1.0",
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
    ]
    existing_paths = [p for p in typelib_paths if os.path.exists(p)]
    if existing_paths:
        os.environ["GI_TYPELIB_PATH"] = ":".join(existing_paths)

try:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    if not adwaita_is_supported(Adw.MAJOR_VERSION, Adw.MINOR_VERSION):
        print(
            f"Нужна libadwaita {MIN_ADWAITA[0]}.{MIN_ADWAITA[1]} или новее, "
            f"установлена {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
        )
        print("Установите пакеты: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1")
        sys.exit(1)

    logger.info("GTK4 imported successfully")

    if not Gtk.init_check():
        logger.error("Gtk.init_check() failed")
        display = Gdk.Display.get_default()
        logger.error(f"Display: {display}")
        print("Не удалось подключиться к дисплею.")
        print("Убедитесь, что запускаете приложение в графическом окружении.")
        sys.exit(1)

    display = Gdk.Display.get_default()
    logger.info(f"Display: {display.get_name() if display else 'None'}")

except ImportError as e:
    logger.exception(f"Error importing GTK: {e}")
    print(f"Ошибка импорта GTK: {e}")
    print("Установите пакеты: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
    sys.exit(1)
except Exception as e:
    logger.exception(f"Error initializing GTK: {e}")
    raise

from src.core.config import (
    BUNDLE_DIR,
    CORE_DIR,
    find_xray_binary,
    get_lock_file,
    init_config_files,
)
from src.sys.single_instance import SingleInstance

logger.info(f"BUNDLE_DIR: {BUNDLE_DIR}")
logger.info(f"CORE_DIR: {CORE_DIR}")
logger.info(f"xray-core path: {find_xray_binary()}")

init_config_files()


def main() -> int:
    args = _ARGS

    # Check for single instance
    lock_file = get_lock_file(args.config_dir)
    single_instance = SingleInstance(lock_file)

    if single_instance.is_running():
        logger.info("Another instance is already running, sending activation signal")
        if single_instance.send_activation_signal():
            logger.info("Activation signal sent successfully")
            return 0

        logger.warning("Could not send activation signal, starting new instance")
        if not single_instance.acquire():
            logger.error("Failed to acquire lock")
            return 1
    elif not single_instance.acquire():
        logger.error("Failed to acquire lock")
        return 1

    try:
        from src.ui.application import run_app

        return run_app(
            config_dir=args.config_dir, lock=single_instance, with_tray=not args.no_tray
        )
    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        print("\nУбедитесь, что установлены зависимости:")
        print("  pip install PyGObject")
        print("  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
        return 1
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        single_instance.release()


if __name__ == "__main__":
    sys.exit(main())
