"""Connection status card shown above the page stack."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango

from src.core.config import get_asset_path
from src.ui.logic.status import SWITCH_LABEL, StatusView, action_hint, switch_hint

logger = logging.getLogger("tenga.ui.status_card")

LOGO_ASSET = "logo-inner-256.png"
LOGO_SIZE = 72
LOGO_SIZE_COMPACT = 48
# Картинка грузится с запасом: на HiDPI и при смене размера она не размывается.
LOGO_LOAD_SIZE = LOGO_SIZE * 2
BADGE_SIZE = 24

_STATE_CLASSES = (
    "status-disconnected",
    "status-connecting",
    "status-connected",
    "status-error",
)


def _load_logo_textures() -> tuple[Gdk.Texture, Gdk.Texture] | None:
    """Load the logo once, in colour and desaturated.

    Обесцвеченный вариант готовится заранее, а не на каждой смене состояния:
    `saturate_and_pixelate` работает по пикселям, и в GTK4 нет CSS-фильтра,
    который сделал бы то же самое для `Gtk.Image` с текстурой.

    Возвращает None, если файла нет: карточка тогда покажет системную иконку,
    а не останется без иконки вовсе.
    """
    path = get_asset_path(LOGO_ASSET)
    try:
        colour = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), LOGO_LOAD_SIZE, LOGO_LOAD_SIZE)
    except GLib.Error as exc:
        logger.warning("Logo %s not loaded, falling back to a themed icon: %s", path, exc)
        return None

    grey = colour.copy()
    colour.saturate_and_pixelate(grey, 0.0, False)

    return Gdk.Texture.new_for_pixbuf(colour), Gdk.Texture.new_for_pixbuf(grey)


class StatusCard(Gtk.Box):
    """Card showing the connection state; the logo is the primary action button."""

    __gtype_name__ = "TengaStatusCard"

    __gsignals__ = {
        "action-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "switch-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("card")
        self.add_css_class("status-card")
        self.set_margin_top(12)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self._logo = _load_logo_textures()
        self._button_label = ""
        self._metric_labels: dict[str, tuple[Gtk.FlowBoxChild, Gtk.Label]] = {}

        self.logo_image = Gtk.Image(pixel_size=LOGO_SIZE)
        self.logo_image.add_css_class("status-icon")

        self._spinner = Gtk.Spinner(halign=Gtk.Align.END, valign=Gtk.Align.END)
        self._spinner.set_size_request(BADGE_SIZE, BADGE_SIZE)

        self._warning = Gtk.Image(
            icon_name="dialog-warning-symbolic",
            pixel_size=BADGE_SIZE,
            halign=Gtk.Align.END,
            valign=Gtk.Align.END,
            visible=False,
        )
        self._warning.add_css_class("status-warning")

        overlay = Gtk.Overlay(child=self.logo_image)
        overlay.add_overlay(self._spinner)
        overlay.add_overlay(self._warning)

        self.logo_button = Gtk.Button(child=overlay, valign=Gtk.Align.CENTER)
        self.logo_button.add_css_class("flat")
        self.logo_button.add_css_class("logo-button")
        self.logo_button.connect("clicked", lambda _button: self.emit("action-clicked"))
        self.append(self.logo_button)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        self._title = Gtk.Label(xalign=0.0, wrap=True)
        self._title.add_css_class("heading")
        text_box.append(self._title)

        self._subtitle = Gtk.Label(xalign=0.0)
        self._subtitle.add_css_class("dim-label")
        self._subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(self._subtitle)

        # Режим и метрики идут одной строкой и переносятся на узком окне: столбики
        # подняли бы карточку над вкладками, а хватает короткой подписи рядом.
        self._metrics = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            focusable=False,
            homogeneous=False,
            column_spacing=12,
            min_children_per_line=1,
            max_children_per_line=4,
        )
        self._metrics.add_css_class("status-metrics")
        self._mode_child, self._mode = self._metric_cell()
        text_box.append(self._metrics)

        self._health = Gtk.Label(xalign=0.0, visible=False)
        self._health.add_css_class("caption")
        self._health.add_css_class("dim-label")
        self._health.set_wrap(True)
        text_box.append(self._health)

        # Выделение другой строки соединение не меняет: переход на неё —
        # отдельное явное действие, видимое только пока выбран не активный.
        # Под текстом, а не в ряд: длинная подпись не должна расширять окно.
        self.switch_button = Gtk.Button(label=SWITCH_LABEL, visible=False)
        self.switch_button.set_halign(Gtk.Align.START)
        self.switch_button.set_margin_top(4)
        self.switch_button.connect("clicked", lambda _button: self.emit("switch-clicked"))
        text_box.append(self.switch_button)

        self.append(text_box)

    def _metric_cell(self) -> tuple[Gtk.FlowBoxChild, Gtk.Label]:
        label = Gtk.Label(xalign=0.0)
        label.add_css_class("metrics")
        label.add_css_class("dim-label")
        child = Gtk.FlowBoxChild(child=label, focusable=False)
        self._metrics.append(child)
        return child, label

    def update(self, view: StatusView) -> None:
        """Render the given view, replacing the classes of the previous state."""
        self._title.set_text(view.title)

        self._subtitle.set_text(view.subtitle)
        self._subtitle.set_visible(bool(view.subtitle))

        self._mode.set_text(view.mode)
        self._mode_child.set_visible(bool(view.mode))
        self._set_metrics(view.metric_items)
        self._metrics.set_visible(bool(view.mode or view.metric_items))

        self._set_logo(view)
        self._warning.set_visible(view.css_class == "status-error")

        self._spinner.set_visible(view.show_spinner)
        if view.show_spinner:
            self._spinner.start()
        else:
            self._spinner.stop()

        for css_class in _STATE_CLASSES:
            self.remove_css_class(css_class)
        self.add_css_class(view.css_class)

        self._button_label = view.button_label
        self.logo_button.update_property([Gtk.AccessibleProperty.LABEL], [view.button_label])
        self.logo_button.set_tooltip_text(action_hint(view))
        self.logo_button.set_sensitive(view.action_enabled)

    def _set_metrics(self, items: tuple[tuple[str, str], ...]) -> None:
        """Show the given values; cells stay in place so traffic ticks do not flicker."""
        values = dict(items)
        for caption in values:
            if caption not in self._metric_labels:
                self._metric_labels[caption] = self._metric_cell()
        for caption, (child, label) in self._metric_labels.items():
            label.set_text(f"{caption} {values[caption]}" if caption in values else "")
            child.set_visible(caption in values)

    def set_switch_target(self, name: str, *, enabled: bool) -> None:
        """Offer to switch to the named server; an empty name hides the button."""
        self.switch_button.set_visible(bool(name))
        self.switch_button.set_tooltip_text(switch_hint(name) if name else None)
        self.switch_button.set_sensitive(enabled)

    def set_health(self, text: str) -> None:
        """Show the monitor's verdict or the last failure; empty hides it."""
        self._health.set_text(text)
        self._health.set_visible(bool(text))

    def _set_logo(self, view: StatusView) -> None:
        """Show the dove in colour or desaturated, else a themed icon if it failed to load."""
        if self._logo is None:
            self.logo_image.set_from_icon_name(view.icon_name)
            return

        colour, grey = self._logo
        self.logo_image.add_css_class("status-logo")
        self.logo_image.set_from_paintable(grey if view.logo_desaturated else colour)

    # Аксессоры для тестов: читать состояние виджета иначе неудобно.

    def get_title(self) -> str:
        return self._title.get_text()

    def get_subtitle(self) -> str:
        return self._subtitle.get_text()

    def get_mode(self) -> str:
        return self._mode.get_text()

    def get_metrics(self) -> list[str]:
        return [
            label.get_text() for child, label in self._metric_labels.values() if child.get_visible()
        ]

    def get_health(self) -> str:
        return self._health.get_text()

    def get_button_label(self) -> str:
        return self._button_label

    def is_spinning(self) -> bool:
        return self._spinner.get_visible()

    def shows_logo(self) -> bool:
        return self.logo_image.get_storage_type() == Gtk.ImageType.PAINTABLE
