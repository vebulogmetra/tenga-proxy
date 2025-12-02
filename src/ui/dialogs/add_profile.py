from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import gi
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, Gdk
from src.fmt import parse_link

if TYPE_CHECKING:
    from src.fmt import ProxyBean


class AddProfileDialog(Gtk.Dialog):
    """Dialog for adding profile by share link."""
    
    def __init__(self, parent: Optional[Gtk.Window] = None):
        super().__init__(
            title="Добавить профиль",
            transient_for=parent,
            flags=0,
        )
        
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_ADD, Gtk.ResponseType.OK,
        )
        
        self.set_default_size(500, 200)
        self.set_modal(True)
        
        self._link_entry: Optional[Gtk.Entry] = None
        self._name_entry: Optional[Gtk.Entry] = None
        self._error_label: Optional[Gtk.Label] = None
        self._parsed_bean: Optional['ProxyBean'] = None
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup UI."""
        content = self.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(15)
        content.set_margin_end(15)
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        
        # Instructions
        info_label = Gtk.Label()
        info_label.set_markup(
            "<b>Вставьте share link профиля</b>\n"
            "<small>Поддерживаются: VLESS, Trojan, VMess, Shadowsocks, SOCKS, HTTP</small>"
        )
        info_label.set_halign(Gtk.Align.START)
        content.pack_start(info_label, False, False, 0)
        # Link field
        link_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(link_box, False, False, 5)
        
        link_label = Gtk.Label(label="Ссылка:")
        link_label.set_width_chars(10)
        link_label.set_halign(Gtk.Align.END)
        link_box.pack_start(link_label, False, False, 0)
        
        self._link_entry = Gtk.Entry()
        self._link_entry.set_placeholder_text("vless://... или trojan://... или vmess://...")
        self._link_entry.connect("changed", self._on_link_changed)
        self._link_entry.connect("activate", self._on_link_activate)
        link_box.pack_start(self._link_entry, True, True, 0)
        
        # Paste button
        paste_button = Gtk.Button(label="[Paste]")
        paste_button.set_tooltip_text("Вставить из буфера обмена")
        paste_button.connect("clicked", self._on_paste_clicked)
        link_box.pack_start(paste_button, False, False, 0)
        # Name field (optional)
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.pack_start(name_box, False, False, 5)
        
        name_label = Gtk.Label(label="Имя:")
        name_label.set_width_chars(10)
        name_label.set_halign(Gtk.Align.END)
        name_box.pack_start(name_label, False, False, 0)
        
        self._name_entry = Gtk.Entry()
        self._name_entry.set_placeholder_text("(опционально, будет взято из ссылки)")
        name_box.pack_start(self._name_entry, True, True, 0)
        # Error/status
        self._error_label = Gtk.Label()
        self._error_label.set_halign(Gtk.Align.START)
        content.pack_start(self._error_label, False, False, 5)
        
        content.show_all()
        
        # Focus on link field
        self._link_entry.grab_focus()
    
    def _on_link_changed(self, entry: Gtk.Entry) -> None:
        """Handle link change."""
        link = entry.get_text().strip()
        
        if not link:
            self._error_label.set_text("")
            self._parsed_bean = None
            return

        bean = parse_link(link)
        
        if bean:
            self._parsed_bean = bean
            self._error_label.set_markup(
                f'<span color="green">[OK] {bean.proxy_type.upper()}: {bean.display_address}</span>'
            )
            
            # Fill name if empty
            if not self._name_entry.get_text() and bean.name:
                self._name_entry.set_text(bean.name)
        else:
            self._parsed_bean = None
            self._error_label.set_markup(
                '<span color="red">[ERROR] Не удалось распарсить ссылку</span>'
            )
    
    def _on_link_activate(self, entry: Gtk.Entry) -> None:
        """Enter in link field."""
        if self._parsed_bean:
            self.response(Gtk.ResponseType.OK)
    
    def _on_paste_clicked(self, button: Gtk.Button) -> None:
        """Paste from clipboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if text:
            self._link_entry.set_text(text.strip())
    
    def get_profile(self) -> Optional['ProxyBean']:
        """Get parsed profile."""
        if not self._parsed_bean:
            return None
        
        # Update name if set
        custom_name = self._name_entry.get_text().strip()
        if custom_name:
            self._parsed_bean.name = custom_name
        
        return self._parsed_bean
    
    def get_link(self) -> str:
        """Get entered link."""
        return self._link_entry.get_text().strip()


def show_add_profile_dialog(parent: Optional[Gtk.Window] = None) -> Optional['ProxyBean']:
    """
    Show add profile dialog.
    
    Returns:
        ProxyBean if profile added, None if cancelled
    """
    dialog = AddProfileDialog(parent)
    response = dialog.run()
    
    profile = None
    if response == Gtk.ResponseType.OK:
        profile = dialog.get_profile()
    
    dialog.destroy()
    return profile
