"""Фасады src.sys отдают одинаковый набор имён на любой ОС."""

from __future__ import annotations

import importlib
import sys

import pytest

FACADES = ["proxy", "vpn", "resolver", "tun_route", "tun_dns", "single_instance"]


# Linux-модули тянут fcntl и прочее POSIX-only: на Windows не импортируются.
@pytest.mark.skipif(sys.platform == "win32", reason="Linux implementation")
@pytest.mark.parametrize("name", FACADES)
def test_linux_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    linux = importlib.import_module(f"src.sys.linux.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(linux, attr)]

    assert missing == []


WINDOWS_READY = ["proxy", "single_instance"]


@pytest.mark.parametrize("name", WINDOWS_READY)
def test_windows_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    windows = importlib.import_module(f"src.sys.windows.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(windows, attr)]

    assert missing == []
