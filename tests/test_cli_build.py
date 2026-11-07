"""Выбор сценария сборки по ОС."""

from __future__ import annotations

from pathlib import Path

import cli


def test_build_script_on_windows(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert cli.build_script_path().name == "build_windows.sh"


def test_build_script_on_linux(monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert cli.build_script_path().name == "build_deb.sh"


def test_install_is_refused_on_windows(monkeypatch, capsys):
    import argparse

    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert cli.cmd_install(argparse.Namespace(uninstall=False)) == 1
    assert "dist/windows" in capsys.readouterr().out


def test_deb_build_checks_diagnostics_catalog():
    script = Path("core/scripts/build_deb.sh")
    assert "assets/diagnostics/targets.json" in script.read_text(encoding="utf-8")


def test_deb_keeps_the_panel_logo_and_section_icons():
    """Панель рисует голубя из исходника 1024 px, настройки — значки разделов."""
    text = Path("core/scripts/build_deb.sh").read_text(encoding="utf-8")
    assert "assets/logo_inner.png" in text
    assert "assets/icons/ui/general.svg" in text
    removed = next(
        line
        for line in text.splitlines()
        if line.strip().startswith("rm -rf") and "screen-" in line
    )
    assert "logo_inner" not in removed
    assert "assets/icons/win" in text
