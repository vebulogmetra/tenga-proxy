#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path

from src.ui.app import run_app


# for AppIndicator3
if 'GI_TYPELIB_PATH' not in os.environ:
    typelib_paths = [
        '/usr/lib/girepository-1.0',
        '/usr/lib/x86_64-linux-gnu/girepository-1.0',
    ]
    existing_paths = [p for p in typelib_paths if os.path.exists(p)]
    if existing_paths:
        os.environ['GI_TYPELIB_PATH'] = ':'.join(existing_paths)


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
