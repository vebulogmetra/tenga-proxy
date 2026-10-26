"""Видимое имя — Veblock; технические идентификаторы tenga-proxy не меняются.

Что и почему оставлено прежним — docs/plans/2026-10-26-veblock-rebrand.md.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = (
    "src",
    "gui.py",
    "cli.py",
    "svc_main.py",
    "packaging",
    "core/scripts",
    "assets/tenga-proxy.desktop",
    "assets/theme/hicolor/index.theme",
    "Makefile",
)
BINARY = {".png", ".ico", ".svg", ".pyc"}
OLD_NAME = re.compile(r"\bTenga (?:Proxy|CLI)\b")


def _files():
    for entry in SCANNED:
        path = ROOT / entry
        if path.is_file():
            yield path
            continue
        for item in sorted(path.rglob("*")):
            generated = any(p == "__pycache__" or p.endswith(".egg-info") for p in item.parts)
            if item.is_file() and not generated and item.suffix not in BINARY:
                yield item


def test_old_display_name_is_gone():
    hits = []
    for path in _files():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for number, line in enumerate(lines, 1):
            # [InstallDelete] и значение автозапуска в .iss называют старое имя намеренно.
            if path.suffix == ".iss" and (line.startswith("Type:") or "ValueName:" in line):
                continue
            if OLD_NAME.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert hits == []


def test_app_name():
    from src import __app_name__

    assert __app_name__ == "Veblock"


def test_desktop_entry_keeps_the_old_name_searchable():
    text = (ROOT / "assets/tenga-proxy.desktop").read_text(encoding="utf-8")
    assert "Name=Veblock\n" in text
    assert "tenga;" in text.split("Keywords=", 1)[1].splitlines()[0]
    assert "Icon=tenga-proxy\n" in text
    assert "StartupWMClass=tenga-proxy\n" in text


def test_windows_installer_upgrades_the_previous_install():
    text = (ROOT / "packaging/windows/tenga-proxy.iss").read_text(encoding="utf-8")
    assert "AppId={{23089B2F-C5D8-45CE-A943-89C573F63388}" in text
    assert "AppName=Veblock\n" in text
    assert "OutputBaseFilename=veblock-{#AppVersion}-windows-x64-setup" in text
    # Прежние ярлыки «Tenga Proxy» не должны остаться рядом с новыми.
    assert "{autoprograms}\\Tenga Proxy" in text
    assert "{autodesktop}\\Tenga Proxy.lnk" in text
    assert 'ValueName: "Tenga Proxy"' in text  # автозапуск: имя значения прежнее


def test_service_identifiers_are_kept():
    from src.winsvc.server import PIPE_NAME
    from src.winsvc.service import DISPLAY_NAME, SERVICE_NAME

    assert SERVICE_NAME == "TengaProxySvc"
    assert PIPE_NAME == r"\\.\pipe\tenga-proxy-svc"
    assert DISPLAY_NAME == "Veblock"
