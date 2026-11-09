"""Rows of the server list: a two-line server row and a full-width group row."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GObject, Gtk, Pango

from src.ui.logic.profiles_view import ProfileRow, ping_text

ACTIVE_CLASS = "profile-active"
EXPIRED_CLASS = "subscription-expired"
ACTIVE_BADGE = "Подключён"
PING_LABEL = "Пинг"
MENU_TOOLTIP = "Действия"


def _text(*classes: str, **kwargs) -> Gtk.Label:
    label = Gtk.Label(**kwargs)
    for css_class in classes:
        label.add_css_class(css_class)
    return label


class ProfileRowWidget(Gtk.Box):
    """Two-line server row: name; type · address; latency, badge, ping, menu."""

    __gtype_name__ = "TengaProfileRowWidget"

    __gsignals__ = {
        "ping-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "menu-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(spacing=8)
        self.add_css_class("profile-row")
        self.row: ProfileRow | None = None

        # Полоса акцента у активного сервера: цвет — не единственный признак,
        # рядом стоит метка «Подключён».
        self._marker = Gtk.Box(visible=False)
        self._marker.add_css_class("active-marker")
        self.append(self._marker)

        texts = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            hexpand=True,
            valign=Gtk.Align.CENTER,
        )
        self._title = _text("profile-title", xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        self._details = _text("details", "dim-label", xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        texts.append(self._title)
        texts.append(self._details)
        self.append(texts)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        # Плашки как в Qt: задержка приглушена вместе с рамкой, «Подключён»
        # обычным шрифтом, а не мелким.
        self._latency = _text("latency", "dim-label", xalign=0.5)
        self._badge = _text("accent-text", xalign=0.5, visible=False)
        right.append(self._latency)
        right.append(self._badge)
        self.append(right)

        self.ping_button = Gtk.Button(label=PING_LABEL, valign=Gtk.Align.CENTER)
        self.ping_button.add_css_class("flat")
        self.ping_button.connect("clicked", lambda _b: self.emit("ping-clicked"))
        self.append(self.ping_button)

        self.menu_button = Gtk.Button(
            icon_name="view-more-symbolic", tooltip_text=MENU_TOOLTIP, valign=Gtk.Align.CENTER
        )
        self.menu_button.add_css_class("flat")
        self.menu_button.update_property([Gtk.AccessibleProperty.LABEL], [MENU_TOOLTIP])
        self.menu_button.connect("clicked", lambda _b: self.emit("menu-clicked"))
        self.append(self.menu_button)

    def bind(self, row: ProfileRow) -> None:
        self.row = row
        self._title.set_text(row.title)
        self._title.set_tooltip_text(row.title)
        details = " · ".join(part for part in (row.proxy_type.upper(), row.address) if part)
        self._details.set_text(details)
        self._latency.set_text(ping_text(row.latency_ms))
        self._badge.set_text(ACTIVE_BADGE if row.is_active else "")
        self._badge.set_visible(row.is_active)
        self._marker.set_visible(row.is_active)
        if row.is_active:
            self.add_css_class(ACTIVE_CLASS)
        else:
            self.remove_css_class(ACTIVE_CLASS)
        self.ping_button.set_tooltip_text(f"Проверить задержку: {row.title}")

    def get_title(self) -> str:
        return self._title.get_text()

    def get_details(self) -> str:
        return self._details.get_text()

    def get_latency(self) -> str:
        return self._latency.get_text()

    def get_badge(self) -> str:
        return self._badge.get_text() if self._badge.get_visible() else ""


class GroupRowWidget(Gtk.Box):
    """Group header: icon, title, summary, progress bar underneath."""

    __gtype_name__ = "TengaGroupRowWidget"

    def __init__(self) -> None:
        # По центру строки: стрелка `Gtk.TreeExpander` стоит по центру, и
        # прижатое к верху название оказывалось выше неё.
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        self.add_css_class("group-row")
        self.group_id = -1

        line = Gtk.Box(spacing=8)
        self._icon = Gtk.Image()
        line.append(self._icon)
        self._title = _text("profile-group", xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        line.append(self._title)
        # Сводка отдельной меткой: длинное название обрезается, а число
        # серверов и ход проверки остаются видны.
        self._summary = _text(
            "dim-label",
            xalign=0.0,
            hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
        )
        line.append(self._summary)
        self.append(line)

        self.progress = Gtk.ProgressBar(visible=False)
        self.progress.add_css_class("group-ping-progress")
        self.append(self.progress)

    def bind(
        self,
        *,
        group_id: int,
        title: str,
        icon_name: str,
        summary: str,
        fraction: float | None,
        expired: bool = False,
    ) -> None:
        self.group_id = group_id
        self._icon.set_visible(bool(icon_name))
        if icon_name:
            self._icon.set_from_icon_name(icon_name)
        self._title.set_text(title)
        self._title.set_tooltip_text(title)
        self._summary.set_text(f"·  {summary}" if summary else "")
        self._summary.set_tooltip_text(summary or None)
        if expired:
            self._summary.add_css_class(EXPIRED_CLASS)
        else:
            self._summary.remove_css_class(EXPIRED_CLASS)
        self.progress.set_visible(fraction is not None)
        if fraction is not None:
            self.progress.set_fraction(fraction)

    def get_title(self) -> str:
        return self._title.get_text()

    def get_summary(self) -> str:
        return self._summary.get_text().removeprefix("·  ")
