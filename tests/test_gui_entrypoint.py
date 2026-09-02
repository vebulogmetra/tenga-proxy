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


def test_gtk4_flag_defaults_to_false(entry):
    args, _ = entry.parse_args([])
    assert args.gtk4 is False


def test_gtk4_flag_is_accepted(entry):
    args, _ = entry.parse_args(["--gtk4"])
    assert args.gtk4 is True


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
