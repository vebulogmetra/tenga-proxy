"""Вывод ядра доступен подписчикам: служба пересылает его в GUI."""

from __future__ import annotations


def test_output_handler_receives_core_lines(tmp_path, monkeypatch):
    import io
    import logging

    from src.core import xray_manager

    monkeypatch.setattr(xray_manager, "XRAY_LOG_FILE", tmp_path / "xray.log")

    manager = xray_manager.XrayManager.__new__(xray_manager.XrayManager)
    manager._core_log = None
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    manager.add_output_handler(Collect())
    xray_manager._pump_core_output(io.BytesIO(b"first\nsecond\n"), manager._core_logger())

    assert lines == ["first", "second"]


def test_core_output_logger_is_shared_helper(tmp_path, monkeypatch):
    from src.core import xray_manager

    monkeypatch.setattr(xray_manager, "XRAY_LOG_FILE", tmp_path / "xray.log")

    assert xray_manager.core_output_logger() is not None
