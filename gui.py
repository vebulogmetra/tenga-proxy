#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path
import logging


def setup_early_logging():
    log_dir = os.environ.get('TENGA_CONFIG_DIR')
    if not log_dir:
        xdg = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        log_dir = os.path.join(xdg, 'tenga-proxy')
    
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'startup.log')
    
    logging.basicConfig(
        filename=log_file,
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    return logging.getLogger('startup')

logger = setup_early_logging()
logger.info("=== Tenga Proxy starting ===")
logger.info(f"Python: {sys.version}")
logger.info(f"DISPLAY: {os.environ.get('DISPLAY')}")
logger.info(f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY')}")
logger.info(f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE')}")

if 'GI_TYPELIB_PATH' not in os.environ:
    typelib_paths = [
        '/usr/lib/girepository-1.0',
        '/usr/lib/x86_64-linux-gnu/girepository-1.0',
    ]
    existing_paths = [p for p in typelib_paths if os.path.exists(p)]
    if existing_paths:
        os.environ['GI_TYPELIB_PATH'] = ':'.join(existing_paths)

try:
    # Initialize GTK before importing any GTK modules
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk
    logger.info("GTK imported successfully")

    if not Gtk.init_check()[0]:
        logger.error("Gtk.init_check() failed")
        display = Gdk.Display.get_default()
        logger.error(f"Display: {display}")
        print("Не удалось подключиться к дисплею.")
        print("Убедитесь, что запускаете приложение в графическом окружении.")
        sys.exit(1)
    
    display = Gdk.Display.get_default()
    logger.info(f"Display: {display.get_name() if display else 'None'}")
    
except Exception as e:
    logger.exception(f"Error initializing GTK: {e}")
    raise

from src.core.config import init_config_files, find_singbox_binary, BUNDLE_DIR, CORE_DIR
from src.ui.app import run_app

logger.info(f"BUNDLE_DIR: {BUNDLE_DIR}")
logger.info(f"CORE_DIR: {CORE_DIR}")
logger.info(f"sing-box path: {find_singbox_binary()}")

init_config_files()


def main() -> int:   
    parser = argparse.ArgumentParser(
        description='Tenga Proxy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '-c', '--config-dir',
        type=Path,
        help='Директория конфигурации (по умолчанию core/)'
    )
    parser.add_argument(
        '--no-tray',
        action='store_true',
        help='Не показывать иконку в трее'
    )
    parser.add_argument(
        '--version',
        action='version',
        version='Tenga Proxy 1.0.0'
    )
    
    args = parser.parse_args()
    
    try:
        return run_app(config_dir=args.config_dir)
    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        print("\nУбедитесь, что установлены зависимости:")
        print("  pip install PyGObject")
        print("  sudo apt install python3-gi gir1.2-appindicator3-0.1 gir1.2-notify-0.7")
        return 1
    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
