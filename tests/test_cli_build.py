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
