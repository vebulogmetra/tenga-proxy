import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

import pytest

from src.core import logging_utils
from src.core.logging_utils import LOG_RETENTION_DAYS, daily_file_handler, setup_logging

DAY = 24 * 60 * 60


@pytest.fixture
def clean_root_logger():
    """setup_logging вешает обработчики на корневой логгер — снимаем свои."""
    root = logging.getLogger()
    before = list(root.handlers)
    yield root
    for handler in root.handlers[:]:
        if handler not in before:
            root.removeHandler(handler)
            handler.close()


def test_setup_logging_creates_log_file(tmp_path, clean_root_logger):
    log_file = tmp_path / "app.log"

    setup_logging(log_file, level=logging.DEBUG)
    logging.getLogger("tenga.test").info("hello")

    assert log_file.exists()


def test_logs_are_kept_for_three_days():
    assert LOG_RETENTION_DAYS == 3


def test_daily_handler_rotates_at_midnight_and_keeps_two_archives(tmp_path):
    """Сегодняшний файл и два архива — ровно три дня логов."""
    handler = daily_file_handler(tmp_path / "app.log")
    try:
        assert isinstance(handler, TimedRotatingFileHandler)
        assert handler.when == "MIDNIGHT"
        assert handler.backupCount == LOG_RETENTION_DAYS - 1
    finally:
        handler.close()


def test_setup_logging_writes_through_the_daily_handler(tmp_path, clean_root_logger):
    log_file = tmp_path / "app.log"

    setup_logging(log_file)

    handlers = [
        h
        for h in clean_root_logger.handlers
        if isinstance(h, TimedRotatingFileHandler) and h.baseFilename == str(log_file)
    ]
    assert len(handlers) == 1


def test_setup_logging_removes_logs_older_than_three_days(tmp_path, clean_root_logger):
    stale = tmp_path / "xray.log.2026-10-01"
    stale.write_text("old")
    old = time.time() - (LOG_RETENTION_DAYS + 1) * DAY
    os.utime(stale, (old, old))
    fresh = tmp_path / "xray.log.2026-10-08"
    fresh.write_text("new")

    setup_logging(tmp_path / "app.log")

    assert not stale.exists()
    assert fresh.exists()


def test_setup_logging_creates_the_log_directory(tmp_path, clean_root_logger, monkeypatch):
    monkeypatch.setattr(logging_utils, "LOG_DIR", tmp_path / "logs")
    log_file = tmp_path / "logs" / "app.log"

    setup_logging(log_file)
    logging.getLogger("tenga.test").info("hello")

    assert log_file.exists()
