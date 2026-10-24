"""Native tray flags keep checkmarks and release their GDI resources."""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.windows


def test_native_menu_flag_preserves_checked_state():
    import ctypes
    from ctypes import wintypes

    from src.ui.tray.win32.backend import MENUITEMINFOW, NotifyIconWindow
    from src.ui.tray.win32.menu_ops import Entry

    backend = NotifyIconWindow()
    bitmaps = []
    menu = backend._build_menu([Entry(1, "🇷🇺Москва", True, True)], bitmaps)
    try:
        assert len(bitmaps) == 1
        info = MENUITEMINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x81  # MIIM_BITMAP | MIIM_STATE
        query = backend._user32.GetMenuItemInfoW
        query.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            wintypes.BOOL,
            ctypes.POINTER(MENUITEMINFOW),
        ]
        query.restype = wintypes.BOOL
        assert query(menu, 0, True, ctypes.byref(info))
        assert info.hbmpItem == bitmaps[0]
        assert info.fState & 0x8  # MF_CHECKED
    finally:
        backend._user32.DestroyMenu(menu)
        for bitmap in bitmaps:
            backend._gdi32.DeleteObject(bitmap)


def test_failed_flag_loading_keeps_original_label(monkeypatch, tmp_path):
    from src.core import config
    from src.ui.tray.win32.backend import NotifyIconWindow

    backend = NotifyIconWindow()
    monkeypatch.setattr(config, "get_asset_path", lambda _name: tmp_path / "missing.bmp")
    assert backend._menu_flag("🇷🇺Москва") == ("🇷🇺Москва", None)


@pytest.mark.parametrize("fail", [False, True])
def test_menu_bitmaps_are_released_after_closing(fail):
    from src.ui.tray.win32.backend import NotifyIconWindow

    events = []
    backend = NotifyIconWindow.__new__(NotifyIconWindow)
    backend._hwnd = 1

    def build(_ops, bitmaps):
        bitmaps.append(12)
        return 11

    def track(*_args):
        if fail:
            raise RuntimeError("popup failed")
        return 3

    backend._build_menu = build
    backend._user32 = SimpleNamespace(
        GetCursorPos=lambda _point: None,
        SetForegroundWindow=lambda _window: None,
        TrackPopupMenu=track,
        PostMessageW=lambda *_args: None,
        DestroyMenu=lambda _menu: events.append("menu"),
    )
    backend._gdi32 = SimpleNamespace(DeleteObject=lambda _bitmap: events.append("bitmap"))
    if fail:
        with pytest.raises(RuntimeError, match="popup failed"):
            backend.show_menu([])
    else:
        assert backend.show_menu([]) == 3
    assert events == ["menu", "bitmap"]
