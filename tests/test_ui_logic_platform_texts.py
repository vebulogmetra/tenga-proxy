"""Тексты, которые зависят от ОС."""

from __future__ import annotations

from src.core import platform_info
from src.ui.logic import platform_texts


def test_linux_vpn_group(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", False)

    assert platform_texts.vpn_group_title() == "Подключение NetworkManager"


def test_windows_vpn_group(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "Windows" in platform_texts.vpn_group_title()
    assert "WireGuard" in platform_texts.vpn_group_description()


def test_missing_release_asset(monkeypatch):
    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)

    assert "установщик" in platform_texts.missing_release_asset()
