import logging

from src.core.logging_utils import setup_logging


def test_setup_logging_creates_log_file(tmp_path):
    log_file = tmp_path / "app.log"

    setup_logging(log_file, level=logging.DEBUG)

    assert log_file.exists()
