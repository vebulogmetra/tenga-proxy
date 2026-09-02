"""Connection status card shown above the page stack."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GObject, Gtk, Pango

from src.ui.logic.status import StatusView

_STATE_CLASSES = (
    "status-disconnected",
    "status-connecting",
    "status-connected",
    "status-error",
)
_BUTTON_CLASSES = ("suggested-action", "destructive-action")


class StatusCard(Gtk.Box):
    """Card showing the connection state and the primary action button."""

    __gtype_name__ = "TengaStatusCard"

    __gsignals__ = {
        "action-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.add_css_class("card")
        self.add_css_class("status-card")
        self.set_margin_top(12)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self._icon = Gtk.Image(icon_name="network-offline-symbolic", pixel_size=32)
        self._icon.add_css_class("status-icon")
        self.append(self._icon)

        self._spinner = Gtk.Spinner()
        self._spinner.set_valign(Gtk.Align.CENTER)
        self.append(self._spinner)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        self._title = Gtk.Label(xalign=0.0)
        self._title.add_css_class("heading")
        text_box.append(self._title)

        self._subtitle = Gtk.Label(xalign=0.0)
        self._subtitle.add_css_class("dim-label")
        self._subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(self._subtitle)

        self._metrics = Gtk.Label(xalign=0.0)
        self._metrics.add_css_class("metrics")
        self._metrics.add_css_class("dim-label")
        text_box.append(self._metrics)

        self.append(text_box)

        self.action_button = Gtk.Button()
        self.action_button.set_valign(Gtk.Align.CENTER)
        self.action_button.connect("clicked", lambda _button: self.emit("action-clicked"))
        self.append(self.action_button)

    def update(self, view: StatusView) -> None:
        """Render the given view, replacing the classes of the previous state."""
        self._title.set_text(view.title)

        self._subtitle.set_text(view.subtitle)
        self._subtitle.set_visible(bool(view.subtitle))

        self._metrics.set_text(view.metrics)
        self._metrics.set_visible(bool(view.metrics))

        self._icon.set_from_icon_name(view.icon_name)
        self._icon.set_visible(not view.show_spinner)

        self._spinner.set_visible(view.show_spinner)
        if view.show_spinner:
            self._spinner.start()
        else:
            self._spinner.stop()

        for css_class in _STATE_CLASSES:
            self.remove_css_class(css_class)
        self.add_css_class(view.css_class)

        self.action_button.set_label(view.button_label)
        for css_class in _BUTTON_CLASSES:
            self.action_button.remove_css_class(css_class)
        self.action_button.add_css_class(view.button_class)

    # Аксессоры для тестов: читать состояние виджета иначе неудобно.

    def get_title(self) -> str:
        return self._title.get_text()

    def get_subtitle(self) -> str:
        return self._subtitle.get_text()

    def get_metrics(self) -> str:
        return self._metrics.get_text()

    def get_button_label(self) -> str:
        return self.action_button.get_label() or ""

    def is_spinning(self) -> bool:
        return self._spinner.get_visible()
