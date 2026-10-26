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
    from src.core.config import CORE_DIR, GUI_LOG_FILE
    from src.core.logging_utils import setup_logging

    setup_logging(GUI_LOG_FILE, level=logging.DEBUG)
    # Раньше GUI писал в startup.log в корне конфигурации, без ротации.
    try:
        (CORE_DIR / "startup.log").unlink(missing_ok=True)
    except OSError:
        pass
    return logging.getLogger("startup")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Veblock",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c", "--config-dir", type=Path, help="Директория конфигурации (по умолчанию core/)"
    )
    parser.add_argument("uris", nargs="*", help="Ссылки импорта приложения")
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


def gtk_install_hint() -> str:
    from src.core import platform_info

    if platform_info.IS_WINDOWS:
        return "Среда GTK входит в установщик: переустановите Veblock."
    return "Установите пакеты: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"


def recover_network() -> None:
    """Вернуть маршрут по умолчанию, если прошлый сеанс TUN упал.

    Только у процесса, захватившего блокировку: второй экземпляр сейчас же
    завершится, а маршруты первого трогать нельзя.
    """
    from src.sys.tun_route import recover_tun_routes

    log = logging.getLogger("startup")
    try:
        ok, error = recover_tun_routes()
    except Exception:
        log.exception("TUN route recovery crashed")
        return
    if not ok:
        log.warning("Failed to recover TUN routes: %s", error)


def cleanup_legacy_install() -> None:
    """Убрать ярлык прежней AppImage-установки: он перекрывает ярлык пакета.

    Только у запуска из deb-пакета: из исходников разработчик может держать
    AppImage рядом намеренно.
    """
    from src.core import config, platform_info

    if platform_info.IS_WINDOWS or not config.is_packaged():
        return
    from src.sys.linux import legacy_appimage

    log = logging.getLogger("startup")
    try:
        removed = legacy_appimage.remove_appimage_launcher(legacy_appimage.data_home())
    except Exception:
        log.exception("Failed to remove AppImage leftovers")
        return
    for path in removed:
        log.info("Removed AppImage leftover %s", path)


# --- GTK bootstrap ---

logger = setup_early_logging()
logger.info("=== Veblock starting ===")
logger.info(f"Python: {sys.version}")
logger.info(f"DISPLAY: {os.environ.get('DISPLAY')}")
logger.info(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
logger.info(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE')}")

_ARGS, _EXTRA = parse_args()

# Локаль выбирается до импорта GTK: переводы подхватываются при инициализации
# библиотеки, и позже смена переменных уже ничего не даёт.
from src.ui.logic.locale import apply_locale

apply_locale()

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
        print(gtk_install_hint())
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
    print(gtk_install_hint())
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

    lock_file = get_lock_file(args.config_dir)
    single_instance = SingleInstance(lock_file)
    holds_lock = single_instance.acquire()
    if not holds_lock:
        from src.core.platform_info import IS_WINDOWS

        if IS_WINDOWS:
            # Без D-Bus Gio.Application не найдёт первый экземпляр сам.
            from src.sys.windows.activation import pipe_address, send_activation

            delivered = send_activation(pipe_address(str(lock_file)), args.uris)
            return 0 if delivered else 1
        # Приложение всё равно запускается: имя на шине занято первым
        # процессом, он получит `activate` и поднимет окно, а этот процесс
        # сразу завершится. Блокировку он не трогает — xray остаётся один.
        logger.info("Another instance holds the lock, activating its window")

    if holds_lock:
        recover_network()
        cleanup_legacy_install()

    try:
        from src.ui.application import run_app

        return run_app(
            config_dir=args.config_dir,
            lock=single_instance if holds_lock else None,
            lock_path=lock_file,
            with_tray=not args.no_tray,
            uris=args.uris,
        )
    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        print(gtk_install_hint())
        return 1
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if holds_lock:
            single_instance.release()


if __name__ == "__main__":
    sys.exit(main())
