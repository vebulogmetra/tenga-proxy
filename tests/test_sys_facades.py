"""Фасады src.sys отдают одинаковый набор имён на любой ОС."""

from __future__ import annotations

import importlib

import pytest

FACADES = ["proxy", "vpn", "resolver", "tun_route", "tun_dns", "single_instance"]


@pytest.mark.parametrize("name", FACADES)
def test_linux_module_provides_every_facade_name(name):
    facade = importlib.import_module(f"src.sys.{name}")
    linux = importlib.import_module(f"src.sys.linux.{name}")

    missing = [attr for attr in facade.__all__ if not hasattr(linux, attr)]

    assert missing == []
