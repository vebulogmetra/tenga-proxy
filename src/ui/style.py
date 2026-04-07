from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk

_THEME_LOADED = False


def init_ui_theme() -> None:
    """Load the shared application theme once."""
    global _THEME_LOADED
    if _THEME_LOADED:
        return

    css = b"""
    .tenga-main-window,
    .tenga-dialog {
        background: #25272b;
    }

    .tenga-main-window decoration,
    .tenga-dialog decoration {
        border-radius: 12px;
        box-shadow: 0 10px 28px alpha(#000000, 0.35);
    }

    headerbar.tenga-titlebar {
        min-height: 38px;
        background-image: linear-gradient(to bottom, #2f3338, #25292d);
        border-bottom: 1px solid alpha(#ffffff, 0.08);
        box-shadow: inset 0 1px alpha(#ffffff, 0.04);
    }

    headerbar.tenga-titlebar .title {
        font-weight: 700;
    }

    headerbar.tenga-titlebar button {
        border-radius: 999px;
        min-width: 24px;
        min-height: 24px;
        padding: 0;
        background: alpha(#ffffff, 0.08);
    }

    headerbar.tenga-titlebar button:hover {
        background: alpha(#ffffff, 0.16);
    }

    .tenga-root {
        padding: 8px;
    }

    .tenga-card {
        border: 1px solid alpha(#ffffff, 0.08);
        border-radius: 12px;
        background: alpha(#111315, 0.20);
        padding: 8px;
    }

    .tenga-notebook > header {
        background: alpha(#0f1012, 0.55);
        border-radius: 10px;
        margin-bottom: 8px;
    }

    .tenga-notebook > header > tabs > tab {
        border-radius: 8px;
        margin: 4px 3px;
        padding: 6px 10px;
        transition: all 180ms ease;
    }

    .tenga-notebook > header > tabs > tab:checked {
        background: alpha(#16a085, 0.22);
        box-shadow: inset 0 -2px #16a085;
    }

    .tenga-tree {
        border-radius: 10px;
        background: alpha(#0f1012, 0.35);
        padding: 2px;
    }

    .tenga-tree.view:selected {
        background: alpha(#16a085, 0.30);
    }

    .tenga-input {
        border-radius: 8px;
    }

    .tenga-input:focus {
        box-shadow: 0 0 0 2px alpha(#16a085, 0.35);
    }

    .tenga-button {
        border-radius: 9px;
        padding: 7px 12px;
        transition: all 140ms ease;
    }

    .tenga-button:hover {
        background: alpha(#ffffff, 0.10);
    }

    .tenga-button-primary {
        background: alpha(#16a085, 0.30);
    }

    .tenga-button-danger {
        background: alpha(#c0392b, 0.22);
    }

    .tenga-status-connected {
        color: #4caf50;
        font-weight: 700;
    }

    .status-connected {
        color: #4caf50;
        font-weight: 700;
    }

    .status-disconnected {
        color: #9e9e9e;
    }

    .delay-good {
        color: #4caf50;
    }

    .delay-medium {
        color: #ff9800;
    }

    .delay-bad {
        color: #f44336;
    }
    """

    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gdk.Screen.get_default()
    if screen:
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
    _THEME_LOADED = True


def _style_button(button: Gtk.Button) -> None:
    ctx = button.get_style_context()
    ctx.add_class("tenga-button")

    label = (button.get_label() or "").lower()
    if any(word in label for word in ("удал", "очистить")):
        ctx.add_class("tenga-button-danger")
        return

    if any(word in label for word in ("подключ", "добав", "применить")):
        ctx.add_class("tenga-button-primary")


def _walk_and_style(widget: Gtk.Widget) -> None:
    if isinstance(widget, Gtk.Notebook):
        widget.get_style_context().add_class("tenga-notebook")
        widget.set_scrollable(True)

    if isinstance(widget, Gtk.TreeView):
        widget.get_style_context().add_class("tenga-tree")
        widget.set_enable_tree_lines(True)
        widget.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)

    if isinstance(widget, Gtk.Frame):
        widget.get_style_context().add_class("tenga-card")

    if isinstance(widget, Gtk.Button):
        _style_button(widget)

    if isinstance(widget, (Gtk.Entry, Gtk.SpinButton, Gtk.ComboBox, Gtk.ComboBoxText, Gtk.TextView)):
        widget.get_style_context().add_class("tenga-input")

    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            _walk_and_style(child)


def style_widget_tree(root: Gtk.Widget) -> None:
    """Apply shared styling classes to widget tree."""
    init_ui_theme()
    _walk_and_style(root)


def _animate_window(window: Gtk.Window) -> None:
    if getattr(window, "_tenga_animation_connected", False):
        return

    window._tenga_animation_connected = True

    def on_map(widget: Gtk.Window, event: Gdk.Event) -> bool:
        screen = widget.get_screen()
        if not screen or not screen.is_composited():
            return False

        try:
            widget.set_opacity(0.0)
        except Exception:
            return False

        state = {"step": 0}
        steps = 12

        def tick() -> bool:
            state["step"] += 1
            opacity = min(1.0, state["step"] / steps)
            try:
                widget.set_opacity(opacity)
            except Exception:
                return False
            return opacity < 1.0

        GLib.timeout_add(16, tick)
        return False

    window.connect("map-event", on_map)


def style_window(window: Gtk.Window, *, is_dialog: bool = False) -> None:
    """Apply global window styles and animation."""
    init_ui_theme()
    ctx = window.get_style_context()
    ctx.add_class("tenga-dialog" if is_dialog else "tenga-main-window")
    _apply_titlebar(window, is_dialog=is_dialog)
    _animate_window(window)


def _apply_titlebar(window: Gtk.Window, *, is_dialog: bool) -> None:
    if getattr(window, "_tenga_titlebar_applied", False):
        return

    title = window.get_title() or "Tenga Proxy"
    header = Gtk.HeaderBar()
    header.set_show_close_button(True)
    header.set_title(title)
    if not is_dialog:
        header.set_subtitle("Proxy Manager")
    header.get_style_context().add_class("tenga-titlebar")

    window.set_titlebar(header)
    window._tenga_titlebar_applied = True


def style_dialog(dialog: Gtk.Dialog) -> None:
    """Apply style to dialog with action buttons."""
    style_window(dialog, is_dialog=True)
    style_widget_tree(dialog.get_content_area())

    for response in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY, Gtk.ResponseType.ACCEPT):
        button = dialog.get_widget_for_response(response)
        if isinstance(button, Gtk.Button):
            button.get_style_context().add_class("tenga-button")
            button.get_style_context().add_class("tenga-button-primary")

    for response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.CLOSE):
        button = dialog.get_widget_for_response(response)
        if isinstance(button, Gtk.Button):
            button.get_style_context().add_class("tenga-button")
