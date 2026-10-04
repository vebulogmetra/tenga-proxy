"""Ядру передаётся каталог геобаз, если рядом с бинарником их нет."""

from __future__ import annotations

from src.core import xray_manager
from src.core.xray_manager import XrayManager


def start_and_capture_env(monkeypatch, tmp_path, asset_dir):
    captured: dict = {}

    class FakeProcess:
        pid = 1

        def poll(self):
            return None

    def popen(_cmd, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    monkeypatch.setattr(XrayManager, "_wait_for_process_ready", lambda _self, **_k: True)
    monkeypatch.setattr(xray_manager, "XRAY_LOG_FILE", tmp_path / "xray.log")
    monkeypatch.setattr(xray_manager.subprocess, "Popen", popen)
    monkeypatch.setattr(xray_manager, "asset_dir_for_core", lambda _binary: asset_dir)

    manager = XrayManager(binary_path=str(tmp_path / "xray"))
    assert manager.start({"inbounds": [], "outbounds": []}) == (True, "")
    return captured.get("env")


def test_bundled_bases_are_passed_through_the_environment(monkeypatch, tmp_path):
    env = start_and_capture_env(monkeypatch, tmp_path, tmp_path / "bundle")

    assert env["XRAY_LOCATION_ASSET"] == str(tmp_path / "bundle")
    assert "PATH" in env  # остальное окружение сохранено


def test_environment_is_untouched_when_the_core_finds_bases_itself(monkeypatch, tmp_path):
    assert start_and_capture_env(monkeypatch, tmp_path, None) is None
