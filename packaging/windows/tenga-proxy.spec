# PyInstaller spec для Windows (MSYS2 UCRT64). Запуск: core/scripts/build_windows.sh
# Сборка onedir: onefile распаковывался бы во временный каталог при каждом
# запуске, а GTK-рантайм весит под сотню мегабайт.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821 (SPECPATH задаёт PyInstaller)
ASSETS = ROOT / "assets"
CORE_BIN = ROOT / "core" / "bin"

# Скриншоты нужны README, а не приложению.
datas = [
    (str(path), str(Path("assets") / path.parent.relative_to(ASSETS)))
    for path in sorted(ASSETS.rglob("*"))
    if path.is_file() and not path.name.startswith("screen-")
]
datas += [
    (str(CORE_BIN / "geoip.dat"), "core/bin"),
    (str(CORE_BIN / "geosite.dat"), "core/bin"),
]
binaries = [
    (str(CORE_BIN / "xray.exe"), "core/bin"),
    (str(CORE_BIN / "wintun.dll"), "core/bin"),
]

hooksconfig = {
    "gi": {
        "icons": ["Adwaita", "hicolor"],
        "themes": ["Adwaita"],
        "languages": ["ru", "en"],
        "module-versions": {"Gtk": "4.0", "Gdk": "4.0"},
    },
}

gui = Analysis(  # noqa: F821
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["gi.repository.Adw", "gi.repository.Gtk", "gi.repository.Gdk"],
    hooksconfig=hooksconfig,
    excludes=["tkinter", "gi.repository.Gtk3"],
)
gui_pyz = PYZ(gui.pure)  # noqa: F821
gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="tenga-proxy",
    icon=str(ASSETS / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=False,
)

coll = COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    name="tenga-proxy",
)
