"""Tests for the GTK version selection at the entry point."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "gui_entry", Path(__file__).resolve().parents[1] / "gui.py"
)


@pytest.fixture(scope="module")
def entry():
    """Import gui.py without executing its GTK setup.

    Модуль на импорте фиксирует версию GTK, поэтому берётся только его
    разбор аргументов и проверка версии — через отдельную загрузку.
    """
    module = importlib.util.module_from_spec(_SPEC)
    module.__name__ = "gui_entry"
    source = (Path(__file__).resolve().parents[1] / "gui.py").read_text()
    # Выполняется только участок до инициализации GTK.
    marker = "# --- GTK bootstrap ---"
    assert marker in source, "gui.py must mark where GTK initialization starts"
    exec(compile(source.split(marker)[0], "gui.py", "exec"), module.__dict__)
    return module


def test_the_gtk4_flag_is_gone(entry):
    """Версия интерфейса больше не выбирается: GTK4 единственный."""
    args, rest = entry.parse_args(["--gtk4"])
    assert not hasattr(args, "gtk4")
    assert "--gtk4" in rest


def test_existing_flags_still_parse(entry):
    args, _ = entry.parse_args(["--no-tray", "-c", "/tmp/x"])
    assert args.no_tray is True
    assert str(args.config_dir) == "/tmp/x"


def test_unknown_args_are_passed_through(entry):
    _, rest = entry.parse_args(["--gtk4", "--weird"])
    assert "--weird" in rest


@pytest.mark.parametrize(
    ("major", "minor", "ok"),
    [(1, 4, False), (1, 5, True), (1, 6, True), (2, 0, True)],
)
def test_libadwaita_version_gate(entry, major, minor, ok):
    assert entry.adwaita_is_supported(major, minor) is ok


def test_install_hint_mentions_installer_on_windows(entry, monkeypatch):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "apt" not in entry.gtk_install_hint()


def test_recover_network_restores_routes_left_by_a_crash(entry, monkeypatch):
    called = []
    monkeypatch.setattr(
        "src.sys.tun_route.recover_tun_routes", lambda: (called.append(1), (True, ""))[1]
    )

    entry.recover_network()

    assert called == [1]


def test_recover_network_never_blocks_the_start(entry, monkeypatch):
    def boom():
        raise OSError("ip not found")

    monkeypatch.setattr("src.sys.tun_route.recover_tun_routes", boom)

    entry.recover_network()


def test_legacy_cleanup_runs_only_from_the_package(entry, monkeypatch):
    from src.core import config, platform_info

    calls = []
    monkeypatch.setattr(
        "src.sys.linux.legacy_appimage.remove_appimage_launcher",
        lambda home: calls.append(home) or [],
    )
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    monkeypatch.setattr(config, "is_packaged", lambda: False)
    entry.cleanup_legacy_install()
    assert calls == []

    monkeypatch.setattr(config, "is_packaged", lambda: True)
    entry.cleanup_legacy_install()
    assert len(calls) == 1


def test_legacy_cleanup_never_blocks_the_start(entry, monkeypatch):
    from src.core import config, platform_info

    def boom(_home):
        raise PermissionError("read-only home")

    monkeypatch.setattr("src.sys.linux.legacy_appimage.remove_appimage_launcher", boom)
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)
    monkeypatch.setattr(config, "is_packaged", lambda: True)

    entry.cleanup_legacy_install()


# --- выбор интерфейса ---


def test_ui_flag_selects_the_frontend(entry):
    args, _ = entry.parse_args(["--ui", "qt"])

    assert entry.choose_frontend(args.ui) == "qt"


@pytest.mark.parametrize(("is_windows", "expected"), [(True, "qt"), (False, "gtk")])
def test_default_frontend_follows_the_os(entry, monkeypatch, is_windows, expected):
    from src.core import platform_info

    monkeypatch.setattr(platform_info, "IS_WINDOWS", is_windows)

    assert entry.choose_frontend(None) == expected


def test_qt_hint_names_the_dependency_group(entry):
    assert "--extra windows" in entry.install_hint("qt")
    assert entry.install_hint("gtk") == entry.gtk_install_hint()
