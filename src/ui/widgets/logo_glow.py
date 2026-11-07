"""Soft halo drawn under the logo button; its colour names the connection state."""

from __future__ import annotations

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk


class LogoGlow(Gtk.DrawingArea):
    """Radial gradient that fades from the state colour to transparent.

    Отдельный виджет, а не CSS box-shadow у кнопки: тень в Adwaita не
    масштабируется вместе с картинкой и режется рамкой кнопки. Перерисовка —
    только при смене цвета или размера, тики трафика её не трогают.
    """

    __gtype_name__ = "TengaLogoGlow"

    def __init__(self) -> None:
        super().__init__(visible=False, can_target=False)
        self._color: str | None = None
        self.set_draw_func(self._draw)

    def set_color(self, color: str | None) -> None:
        """Set the halo colour; None hides the halo entirely."""
        if color == self._color:
            return
        self._color = color
        self.set_visible(color is not None)
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        if self._color is None:
            return
        rgba = Gdk.RGBA()
        rgba.parse(self._color)
        cx, cy = width / 2, height * 0.55
        radius = min(width, height) * 0.5
        pattern = cairo.RadialGradient(cx, cy, radius * 0.1, cx, cy, radius)
        pattern.add_color_stop_rgba(0.0, rgba.red, rgba.green, rgba.blue, 0.45)
        pattern.add_color_stop_rgba(0.55, rgba.red, rgba.green, rgba.blue, 0.18)
        pattern.add_color_stop_rgba(1.0, rgba.red, rgba.green, rgba.blue, 0.0)
        cr.set_source(pattern)
        cr.rectangle(0, 0, width, height)
        cr.fill()

    def get_color_for_test(self) -> str | None:
        return self._color
