"""Connection panel on the left of the main window: the dove is the primary action."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango

from src.core.config import get_asset_path
from src.ui.logic.appearance import (
    LOGO_SIZE,
    LOGO_SIZE_COMPACT,
    PANEL_MIN_WIDTH,
    glow_color,
)
from src.ui.logic.country_flags import split_flag_prefix
from src.ui.logic.status import StatusView, action_hint
from src.ui.widgets.logo_glow import LogoGlow

logger = logging.getLogger("tenga.ui.status_card")

# Исходник 1024 px: панель показывает голубя крупно, на HiDPI 256 px размывались бы.
LOGO_ASSET = "logo_inner.png"
# Картинка грузится с запасом: на HiDPI и при смене размера она не размывается.
LOGO_LOAD_SIZE = LOGO_SIZE * 2
# Свечение выходит за края картинки: место под него заложено в размер слота.
GLOW_MARGIN = 0.18
FLAG_SIZE = 16
# Порядок столбиков постоянный, как в Qt: пустые скрываются, остальные не сдвигаются.
METRIC_CAPTIONS = ("Задержка", "↓ Получено", "↑ Отправлено")

_STATE_CLASSES = (
    "status-disconnected",
    "status-connecting",
    "status-disconnecting",
    "status-connected",
    "status-error",
    "status-blocked",
    "status-empty",
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


def _label(*classes: str, **kwargs) -> Gtk.Label:
    label = Gtk.Label(justify=Gtk.Justification.CENTER, **kwargs)
    for css_class in classes:
        label.add_css_class(css_class)
    return label


class StatusCard(Gtk.Box):
    """Vertical panel with the connection state; the logo is the primary action button."""

    __gtype_name__ = "TengaStatusCard"

    __gsignals__ = {
        "action-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    # Включает брейкпоинт окна по высоте: логотип и отступы уменьшаются.
    compact = GObject.Property(type=bool, default=False)

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("status-card")
        self.set_size_request(PANEL_MIN_WIDTH, -1)

        self._logo = _load_logo_textures()
        self._button_label = ""
        self._flag_code: str | None = None

        # Свечение рисуется под картинкой: Gtk.Overlay кладёт оверлеи поверх
        # child и друг друга в порядке добавления, поэтому child — пустой слот
        # нужного размера, затем свечение, затем голубь.
        self._logo_slot = Gtk.Box()
        self.glow = LogoGlow()
        self.logo_image = Gtk.Image(
            pixel_size=LOGO_SIZE, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER
        )
        self.logo_image.add_css_class("status-logo")
        overlay = Gtk.Overlay(child=self._logo_slot)
        overlay.add_overlay(self.glow)
        overlay.add_overlay(self.logo_image)

        self.logo_button = Gtk.Button(child=overlay, halign=Gtk.Align.CENTER)
        self.logo_button.add_css_class("flat")
        self.logo_button.add_css_class("logo-button")
        self.logo_button.connect("clicked", lambda _button: self.emit("action-clicked"))
        self.append(self.logo_button)

        self._instruction = _label("caption", "dim-label", wrap=True)
        self.append(self._instruction)

        dot_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=6)
        self.dot = Gtk.Label(label="●")
        self.dot.add_css_class("connection-dot")
        dot_row.append(self.dot)
        self._title = _label("title-2", "status-title", wrap=True)
        dot_row.append(self._title)
        self.append(dot_row)

        self.server_caption = _label("caption", "dim-label", margin_top=6)
        self.append(self.server_caption)

        self._name_row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        self.flag = Gtk.Image(pixel_size=FLAG_SIZE, visible=False)
        self._name_row.append(self.flag)
        self.subtitle_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END)
        self.subtitle_label.add_css_class("heading")
        self._name_row.append(self.subtitle_label)
        self.append(self._name_row)

        self._mode_separator = Gtk.Separator(margin_top=8)
        self.append(self._mode_separator)
        self._mode = _label("dim-label", margin_top=4)
        self.append(self._mode)

        self._metrics = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER, margin_top=6)
        self._metric_columns: dict[str, tuple[Gtk.Box, Gtk.Label]] = {}
        for caption in METRIC_CAPTIONS:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            value = _label("metric-value")
            column.append(value)
            column.append(_label("caption", "dim-label", label=caption))
            self._metrics.append(column)
            self._metric_columns[caption] = (column, value)
        self.append(self._metrics)

        self.append(Gtk.Box(vexpand=True))

        self._health_separator = Gtk.Separator()
        self.append(self._health_separator)
        self.health_label = _label("caption", wrap=True, visible=False)
        self.append(self.health_label)

        self.connect("notify::compact", lambda *_args: self._apply_size())
        self._apply_size()

    def _apply_size(self) -> None:
        compact = self.get_property("compact")
        size = LOGO_SIZE_COMPACT if compact else LOGO_SIZE
        self.logo_image.set_pixel_size(size)
        slot = round(size * (1 + GLOW_MARGIN))
        self._logo_slot.set_size_request(slot, slot)
        if compact:
            self.add_css_class("compact")
        else:
            self.remove_css_class("compact")

    def update(self, view: StatusView) -> None:
        """Render the given view, replacing the classes of the previous state."""
        self._title.set_text(view.title)
        self._set_server(view)

        self._mode.set_text(view.mode)
        self._mode.set_visible(bool(view.mode))
        values = dict(view.metric_items)
        for caption, (column, value) in self._metric_columns.items():
            value.set_text(values.get(caption, ""))
            column.set_visible(caption in values)
        self._metrics.set_visible(bool(values))
        self._mode_separator.set_visible(bool(view.mode or values))

        self._set_logo(view)
        self.glow.set_color(glow_color(view.css_class))

        for widget in (self, self.dot):
            for css_class in _STATE_CLASSES:
                widget.remove_css_class(css_class)
            widget.add_css_class(view.css_class)

        hint = action_hint(view)
        self._instruction.set_text(hint)
        self._button_label = view.button_label
        self.logo_button.update_property([Gtk.AccessibleProperty.LABEL], [view.button_label])
        self.logo_button.set_tooltip_text(hint)
        self.logo_button.set_sensitive(view.action_enabled)

    def _set_server(self, view: StatusView) -> None:
        code, name = split_flag_prefix(view.subtitle)
        flag = get_asset_path(f"flags/{code}.svg") if code else None
        if flag is None or not flag.is_file():
            # Без картинки для кода имя остаётся как есть, с эмодзи.
            code, name = None, view.subtitle
        if code != self._flag_code:
            self._flag_code = code
            if flag is not None and code is not None:
                self.flag.set_from_file(str(flag))
        self.flag.set_visible(code is not None)

        self.subtitle_label.set_text(name)
        self.subtitle_label.set_tooltip_text(view.subtitle or None)
        shown = bool(view.subtitle)
        self._name_row.set_visible(shown)
        self.server_caption.set_visible(shown)
        self.server_caption.set_text(
            "Активный сервер" if view.css_class == "status-connected" else "Сервер"
        )

    def set_health(self, text: str) -> None:
        """Show the monitor's verdict or the last failure; empty hides it."""
        self.health_label.set_text(text)
        self.health_label.set_visible(bool(text))
        self._health_separator.set_visible(bool(text))

    def _set_logo(self, view: StatusView) -> None:
        """Show the dove in colour or desaturated, else a themed icon if it failed to load."""
        if self._logo is None:
            self.logo_image.set_from_icon_name(view.icon_name)
            return

        colour, grey = self._logo
        self.logo_image.set_from_paintable(grey if view.logo_desaturated else colour)

    # Аксессоры для тестов: читать состояние виджета иначе неудобно.

    def get_title(self) -> str:
        return self._title.get_text()

    def get_subtitle(self) -> str:
        return self.subtitle_label.get_text()

    def get_instruction(self) -> str:
        return self._instruction.get_text()

    def get_server_caption(self) -> str:
        return self.server_caption.get_text()

    def get_mode(self) -> str:
        return self._mode.get_text() if self._mode.get_visible() else ""

    def get_metrics(self) -> list[tuple[str, str]]:
        return [
            (caption, value.get_text())
            for caption, (column, value) in self._metric_columns.items()
            if column.get_visible()
        ]

    def get_health(self) -> str:
        return self.health_label.get_text()

    def get_button_label(self) -> str:
        return self._button_label

    def shows_logo(self) -> bool:
        return self.logo_image.get_storage_type() == Gtk.ImageType.PAINTABLE
