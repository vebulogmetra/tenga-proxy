"""Сгенерировать иконки Windows: трей, приложение и логотип карточки статуса.

На Windows логотип — «Монолит»: расколотая каменная колонна со светящимся
ядром, цвет ядра показывает состояние подключения. Рисунок — шаблоны
`packaging/windows/icons/monolith*.svg`, где вместо цветов ядра стоят
подстановки `{core}`, `{light}`, `{glow}`, `{halo}`, `{rim}`. Мелкий шаблон
нужен кадрам до 20 px: на них зубцы скола крупного рисунка закрывают ядро.

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

from src.ui.tray.icons import ICON_CONNECTED, ICON_CONNECTING, ICON_DISCONNECTED
from src.ui.tray.win32.ico import build_ico

TEMPLATES = ROOT / "packaging" / "windows" / "icons"
OUT_DIR = ROOT / "assets" / "icons" / "win"

TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)
APP_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
CARD_SIZE = 128
SMALL_UP_TO = 20

# Ядро бирюзовое, как свечение у референса; при подключении янтарное; без
# подключения угасает до цвета камня, без ореола; при ошибке красное.
PALETTES = {
    "connected": {
        "core": "#12b39a", "light": "#7dffe6", "glow": "#1fe0c0", "halo": "0.55", "rim": "0.9",
    },
    "connecting": {
        "core": "#d98a1c", "light": "#ffd27a", "glow": "#ffae3a", "halo": "0.5", "rim": "0.9",
    },
    "disconnected": {
        "core": "#3b4650", "light": "#66727d", "glow": "#000000", "halo": "0", "rim": "0.4",
    },
    "error": {
        "core": "#c62f2f", "light": "#ff8a7a", "glow": "#ff4040", "halo": "0.5", "rim": "0.9",
    },
}  # fmt: skip

TRAY_STATES = {
    ICON_CONNECTED: "connected",
    ICON_CONNECTING: "connecting",
    ICON_DISCONNECTED: "disconnected",
}


def png_bytes(pixbuf) -> bytes:
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return bytes(data)


def monolith_svg(state: str, size: int) -> bytes:
    name = "monolith-small.svg" if size <= SMALL_UP_TO else "monolith.svg"
    svg = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in PALETTES[state].items():
        svg = svg.replace("{" + key + "}", value)
    return svg.encode("utf-8")


def render(state: str, size: int) -> bytes:
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.set_size(size, size)
    loader.write(monolith_svg(state, size))
    loader.close()
    return png_bytes(loader.get_pixbuf())


def monolith_ico(state: str, sizes) -> bytes:
    return build_ico([(size, render(state, size)) for size in sizes])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for icon_name, state in TRAY_STATES.items():
        (OUT_DIR / f"{icon_name}.ico").write_bytes(monolith_ico(state, TRAY_SIZES))
    for state in PALETTES:
        (OUT_DIR / f"monolith-{state}.png").write_bytes(render(state, CARD_SIZE))
    (ROOT / "assets" / "tenga-proxy.ico").write_bytes(monolith_ico("connected", APP_SIZES))
    print(f"Written to {OUT_DIR} and assets/tenga-proxy.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
