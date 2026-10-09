"""Вывод ядра идёт в суточный лог, а не прямо в файл без ротации."""

from __future__ import annotations

import io
import subprocess

from src.core import xray_manager
from src.core.xray_manager import XrayManager


class FakeProcess:
    pid = 1

    def __init__(self, output: bytes) -> None:
        self.stdout = io.BytesIO(output)
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def make_manager(monkeypatch, tmp_path, output: bytes, ready: bool = True):
    captured: dict = {}

    def popen(_cmd, **kwargs):
        captured.update(kwargs)
        process = FakeProcess(output)
        if not ready:
            process.returncode = 1
        return process

    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    monkeypatch.setattr(XrayManager, "_wait_for_process_ready", lambda _self, **_k: ready)
    monkeypatch.setattr(xray_manager, "XRAY_LOG_FILE", tmp_path / "xray.log")
    monkeypatch.setattr(xray_manager.subprocess, "Popen", popen)
    monkeypatch.setattr(xray_manager, "asset_dir_for_core", lambda _binary: None)
    return XrayManager(binary_path=str(tmp_path / "xray")), captured


def test_core_output_is_piped_not_handed_a_file(monkeypatch, tmp_path):
    manager, captured = make_manager(monkeypatch, tmp_path, b"")

    manager.start({"inbounds": [], "outbounds": []})
    manager.stop()

    assert captured["stdout"] is subprocess.PIPE
    assert captured["stderr"] is subprocess.STDOUT


def test_core_output_lands_in_the_log_file(monkeypatch, tmp_path):
    manager, _ = make_manager(monkeypatch, tmp_path, b"Xray 26.9.9 started\nsecond line\n")

    assert manager.start({"inbounds": [], "outbounds": []}) == (True, "")
    manager.stop()

    assert (tmp_path / "xray.log").read_text(encoding="utf-8") == (
        "Xray 26.9.9 started\nsecond line\n"
    )


def test_failed_start_keeps_the_core_error_in_the_log(monkeypatch, tmp_path):
    output = b"Failed to start: app/proxyman/inbound: failed to start proxy > busy\n"
    manager, _ = make_manager(monkeypatch, tmp_path, output, ready=False)

    ok, _error = manager.start({"inbounds": [], "outbounds": []})

    assert not ok
    assert "Failed to start" in (tmp_path / "xray.log").read_text(encoding="utf-8")


def test_restarts_reuse_one_log_handler(monkeypatch, tmp_path):
    """Повторный запуск не должен дублировать строки вторым обработчиком."""
    manager, _ = make_manager(monkeypatch, tmp_path, b"line\n")

    manager.start({"inbounds": [], "outbounds": []})
    manager.stop()
    manager.start({"inbounds": [], "outbounds": []})
    manager.stop()

    assert (tmp_path / "xray.log").read_text(encoding="utf-8") == "line\nline\n"
