"""Сгенерировать .ico для Windows из SVG трея и PNG приложения.

Запуск на машине разработчика (нужен GdkPixbuf с загрузчиком SVG):
    uv run python tools/make_ico.py
Результат коммитится: сборка на Windows SVG не рендерит.
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.ui.tray.icons import ICON_NAMES
from src.ui.tray.win32.ico import build_ico

TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)
APP_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(pixbuf) -> bytes:
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return bytes(data)


def from_file(path: Path, sizes) -> bytes:
    frames = [
        (size, png_bytes(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)))
        for size in sizes
    ]
    return build_ico(frames)


def main() -> int:
    out_dir = ROOT / "assets" / "icons" / "win"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ICON_NAMES:
        (out_dir / f"{name}.ico").write_bytes(
            from_file(ROOT / "assets" / "icons" / f"{name}.svg", TRAY_SIZES)
        )
    app_png = ROOT / "assets" / "theme" / "hicolor" / "256x256" / "apps" / "tenga-proxy.png"
    (ROOT / "assets" / "tenga-proxy.ico").write_bytes(from_file(app_png, APP_SIZES))
    print(f"Written to {out_dir} and assets/tenga-proxy.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
