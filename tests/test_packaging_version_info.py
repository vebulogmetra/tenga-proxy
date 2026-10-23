"""Ресурс версии exe для PyInstaller на Windows."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "version_info.py"
_SPEC = importlib.util.spec_from_file_location("version_info", _PATH)
version_info = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(version_info)


def test_version_tuple_has_four_numbers():
    assert version_info.version_tuple("0.17.0") == (0, 17, 0, 0)


def test_version_tuple_ignores_suffixes():
    assert version_info.version_tuple("1.2.3rc1") == (1, 2, 3, 0)


def test_render_names_product_and_version():
    text = version_info.render("0.17.0")

    assert "filevers=(0, 17, 0, 0)" in text
    assert "StringStruct('ProductName', 'Tenga Proxy')" in text
    assert "StringStruct('ProductVersion', '0.17.0')" in text


def test_render_is_python_syntax():
    compile(version_info.render("0.17.0"), "version_info.txt", "eval")


def test_project_version_is_read_from_sources():
    assert version_info.project_version().count(".") == 2
