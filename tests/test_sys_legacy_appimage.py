"""Следы прежней AppImage-установки в домашнем каталоге."""

from __future__ import annotations

from src.sys.linux import legacy_appimage

APPIMAGE_DESKTOP = """[Desktop Entry]
Name=Tenga Proxy
Exec="/home/user/.local/bin/tenga-proxy.AppImage" %U
Icon=tenga-proxy
"""


def _icons(data_home):
    return [
        data_home / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "tenga-proxy.png"
        for size in (64, 128, 256)
    ]


def _install_appimage_leftovers(data_home, desktop_text=APPIMAGE_DESKTOP):
    desktop = data_home / "applications" / "tenga-proxy.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(desktop_text)
    for icon in _icons(data_home):
        icon.parent.mkdir(parents=True)
        icon.write_bytes(b"png")
    return desktop


def test_appimage_launcher_and_its_icons_are_removed(tmp_path):
    desktop = _install_appimage_leftovers(tmp_path)

    removed = legacy_appimage.remove_appimage_launcher(tmp_path)

    assert not desktop.exists()
    assert not any(icon.exists() for icon in _icons(tmp_path))
    assert set(removed) == {desktop, *_icons(tmp_path)}


def test_users_own_launcher_is_kept(tmp_path):
    """Ярлык, который пользователь написал сам, указывает не на AppImage."""
    desktop = _install_appimage_leftovers(
        tmp_path, "[Desktop Entry]\nName=Tenga Proxy\nExec=tenga-proxy --no-tray %U\n"
    )

    assert legacy_appimage.remove_appimage_launcher(tmp_path) == []
    assert desktop.exists()
    assert all(icon.exists() for icon in _icons(tmp_path))


def test_nothing_to_remove_without_a_launcher(tmp_path):
    assert legacy_appimage.remove_appimage_launcher(tmp_path) == []


def test_data_home_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert legacy_appimage.data_home() == tmp_path / "data"

    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert legacy_appimage.data_home() == tmp_path / ".local" / "share"
