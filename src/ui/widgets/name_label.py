"""Windows name labels with bundled country flags instead of font-dependent emoji."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from src.core.config import get_asset_path
from src.ui.logic import platform_layout
from src.ui.logic.country_flags import flag_parts


class FlagNameLabel(Gtk.Box):
    """Keep the original text for accessibility and show a flag image alongside it."""

    def __init__(self, *, xalign: float = 0.0) -> None:
        super().__init__(spacing=0)
        self._text = ""
        self._ellipsize = Pango.EllipsizeMode.NONE
        self._xalign = xalign
        self._flag = Gtk.Image(pixel_size=24, visible=False)
        self._label = Gtk.Label(xalign=xalign, hexpand=True)
        self.append(self._flag)
        self.append(self._label)

    def set_text(self, text: str) -> None:
        self._text = text
        child = self.get_first_child()
        while child is not None:
            self.remove(child)
            child = self.get_first_child()
        self._flag.clear()
        self._flag.set_visible(False)
        pending = ""
        used_flag = False
        for code, value in flag_parts(text):
            texture = self._load_flag(code) if code else None
            if texture is None:
                pending += value
                continue
            if pending:
                label = Gtk.Label(xalign=self._xalign)
                self._set_label_text(label, pending)
                self.append(label)
                pending = ""
            flag = Gtk.Image(pixel_size=24) if used_flag else self._flag
            flag.set_from_paintable(texture)
            flag.set_visible(True)
            flag.set_margin_end(4)
            self.append(flag)
            used_flag = True
        if not used_flag:
            self.append(self._flag)
        self._set_label_text(self._label, pending)
        self._label.set_ellipsize(self._ellipsize)
        self.append(self._label)
        self.set_tooltip_text(text or None)
        self.update_property([Gtk.AccessibleProperty.LABEL], [text])

    @staticmethod
    def _set_label_text(label: Gtk.Label, text: str) -> None:
        label.set_text(text)
        attrs = Pango.AttrList()
        offset = 0
        for char in text:
            end = offset + len(char.encode("utf-8"))
            # Explicitly select Windows' emoji font for symbols such as ☄.
            # Pango indices count UTF-8 bytes, including after Cyrillic text.
            if 0x2600 <= ord(char) <= 0x27BF or 0x1F000 <= ord(char) <= 0x1FAFF:
                attr = Pango.attr_family_new("Segoe UI Emoji")
                attr.start_index, attr.end_index = offset, end
                attrs.insert(attr)
            offset = end
        label.set_attributes(attrs)

    @staticmethod
    def _load_flag(code: str) -> Gdk.Texture | None:
        # Use the same raster assets as the native tray. Gtk.Image's SVG
        # renderer and its loaders vary between installed GTK runtimes.
        path = get_asset_path(f"flags/win/{code}.bmp")
        texture = None
        if path is not None and path.is_file():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            except GLib.Error:
                pass
        return texture

    def get_text(self) -> str:
        return self._text

    def set_ellipsize(self, mode: Pango.EllipsizeMode) -> None:
        self._ellipsize = mode
        self._label.set_ellipsize(mode)


def name_label(*, xalign: float = 0.0) -> Gtk.Label | FlagNameLabel:
    if platform_layout.bundled_flag_images():
        return FlagNameLabel(xalign=xalign)
    return Gtk.Label(xalign=xalign)
