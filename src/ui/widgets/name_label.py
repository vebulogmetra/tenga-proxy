"""Windows name labels with bundled country flags instead of font-dependent emoji."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from src.core.config import get_asset_path
from src.ui.logic import platform_layout
from src.ui.logic.country_flags import split_flag_prefix


class FlagNameLabel(Gtk.Box):
    """Keep the original text for accessibility and show a flag image alongside it."""

    def __init__(self, *, xalign: float = 0.0) -> None:
        super().__init__(spacing=6)
        self._text = ""
        self._flag = Gtk.Image(pixel_size=24, visible=False)
        self._label = Gtk.Label(xalign=xalign, hexpand=True)
        self.append(self._flag)
        self.append(self._label)

    def set_text(self, text: str) -> None:
        self._text = text
        code, title = split_flag_prefix(text)
        # Use the same raster assets as the native tray. Gtk.Image's SVG
        # renderer and its loaders vary between installed GTK runtimes.
        path = get_asset_path(f"flags/win/{code}.bmp") if code else None
        texture = None
        if path is not None and path.is_file():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            except GLib.Error:
                pass
        has_flag = texture is not None
        self._flag.set_visible(has_flag)
        if has_flag:
            self._flag.set_from_paintable(texture)
        else:
            self._flag.clear()
        self._label.set_text(title if has_flag else text)
        self.set_tooltip_text(text or None)
        self.update_property([Gtk.AccessibleProperty.LABEL], [text])

    def get_text(self) -> str:
        return self._text

    def set_ellipsize(self, mode: Pango.EllipsizeMode) -> None:
        self._label.set_ellipsize(mode)


def name_label(*, xalign: float = 0.0) -> Gtk.Label | FlagNameLabel:
    if platform_layout.bundled_flag_images():
        return FlagNameLabel(xalign=xalign)
    return Gtk.Label(xalign=xalign)
