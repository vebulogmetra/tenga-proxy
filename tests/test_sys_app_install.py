"""Запуск установщика: UAC через подменённый runas, наблюдатель перезапуска."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.app_installer import InstallCancelled
from src.sys.linux import app_install as linux_install
from src.sys.windows import app_install

INSTALLER_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


def test_linux_never_self_updates():
    assert linux_install.can_self_update() is False
    with pytest.raises(NotImplementedError):
        linux_install.launch_installer(Path("setup.exe"))


def test_windows_self_update_needs_the_frozen_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_install.can_self_update() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert app_install.can_self_update() is True


def test_launch_runs_the_installer_silently_and_leaves_a_relaunch_watcher():
    calls = []

    app_install.launch_installer(
        Path(r"C:\tmp\veblock-setup.exe"),
        runas=lambda path, args: calls.append(("runas", path, args)) or 4242,
        spawn=lambda command: calls.append(("spawn", command)),
        executable=r"C:\Program Files\Veblock\tenga-proxy.exe",
    )

    assert calls[0] == ("runas", r"C:\tmp\veblock-setup.exe", INSTALLER_ARGS)
    kind, command = calls[1]
    assert kind == "spawn"
    assert command[:5] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
    ]
    assert "Get-Process -Id 4242" in command[-1]
    assert "Start-Process -FilePath 'C:\\Program Files\\Veblock\\tenga-proxy.exe'" in command[-1]


def test_uac_refusal_leaves_no_watcher():
    def refuse(_path, _args):
        raise InstallCancelled("нет")

    spawned = []
    with pytest.raises(InstallCancelled):
        app_install.launch_installer(Path("setup.exe"), runas=refuse, spawn=spawned.append)

    assert spawned == []


def test_relaunch_command_escapes_single_quotes():
    command = app_install.relaunch_command(7, "C:\\O'Neil\\app.exe")

    assert "'C:\\O''Neil\\app.exe'" in command[-1]
