"""Generate native Windows menu bitmaps from the bundled SVG flags (MSYS2 Python)."""

from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

ROOT = Path(__file__).resolve().parents[1] / "assets" / "flags"


def main() -> None:
    target = ROOT / "win"
    target.mkdir(exist_ok=True)
    for source in sorted(ROOT.glob("??.svg")):
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), 32, 24, True)
        pixbuf.savev(str(target / f"{source.stem}.bmp"), "bmp", [], [])


if __name__ == "__main__":
    main()
