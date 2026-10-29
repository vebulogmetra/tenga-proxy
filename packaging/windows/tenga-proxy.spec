# PyInstaller spec для Windows. Запуск: core/scripts/build_windows.sh
# Сборка onedir: onefile распаковывался бы во временный каталог при каждом
# запуске, а библиотеки Qt весят десятки мегабайт.

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
    (str(ROOT / "src" / "ui" / "qt" / "style.qss"), "src/ui/qt"),
    (str(CORE_BIN / "geoip.dat"), "core/bin"),
    (str(CORE_BIN / "geosite.dat"), "core/bin"),
]
binaries = [
    (str(CORE_BIN / "xray.exe"), "core/bin"),
    (str(CORE_BIN / "wintun.dll"), "core/bin"),
]

# Интерфейс Windows — Qt. GTK-модули gui.py импортирует только для `--ui gtk`,
# в сборке их нет. Модули Qt, которых приложение не импортирует, исключены на
# случай, если их потянет зависимость; QtNetwork нужен failover
# (QNetworkInformation).
QT_UNUSED = [
    "PySide6.QtConcurrent",
    "PySide6.QtDBus",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
]

gui = Analysis(  # noqa: F821
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    excludes=["tkinter", "gi", "cairo", *QT_UNUSED],
)
# Режим UTF-8: иначе open()/read_text() без encoding читали бы в cp1252.
PYTHON_OPTIONS = [("X utf8_mode=1", None, "OPTION")]

gui_pyz = PYZ(gui.pure)  # noqa: F821
gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    PYTHON_OPTIONS,
    exclude_binaries=True,
    name="tenga-proxy",
    icon=str(ASSETS / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=False,
)

# Служба: свой exe в том же каталоге, интерфейс ей не нужен. Если анализ всё же
# находит PySide6 или gi, какой-то импорт в src.core стоит сделать ленивым.
svc = Analysis(  # noqa: F821
    [str(ROOT / "svc_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    hiddenimports=["win32timezone", "servicemanager"],
    excludes=["tkinter", "gi", "cairo", "PySide6", "shiboken6"],
)
svc_pyz = PYZ(svc.pure)  # noqa: F821
svc_exe = EXE(  # noqa: F821
    svc_pyz,
    svc.scripts,
    PYTHON_OPTIONS,
    exclude_binaries=True,
    name="tenga-proxy-svc",
    icon=str(ASSETS / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=True,
)

coll = COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    svc_exe,
    svc.binaries,
    svc.datas,
    name="tenga-proxy",
)
